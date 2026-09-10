"""Parsing helpers for RSS/Atom feed content.

This module is intentionally free of network and config-entry concerns so it can
be exercised directly by the test suite against the fixtures in `tests/data`.
"""

from __future__ import annotations

import email.utils
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timezone
from typing import Any
from urllib.parse import urljoin

import feedparser  # type: ignore[import]
from dateutil import parser as dateutil_parser
from feedparser import FeedParserDict
from homeassistant.util import dt

from .const import (
    DEFAULT_MAX_TEXT_LENGTH,
    IMAGE_REGEX,
    MAX_STATE_ATTRS_BYTES,
    NO_TEXT_LIMIT,
    TRUNCATION_SUFFIX,
    UNTRUNCATED_KEYS,
)
from .sanitize import safe_url, sanitize_mapping

_LOGGER: logging.Logger = logging.getLogger(__name__)

DATE_KEYS = ("published", "updated", "created", "expired")

# Feed key -> the (show_topn, max_text_length) the oversize warning was last
# logged for, so a polled feed does not repeat the same line forever.
_OVERSIZED_WARNED: dict[str, tuple[int, int]] = {}

# A tag, or - at the very end of a value - the start of one that never closes.
TAG_REGEX = re.compile(r"<[^>]*(?:>|$)")
ENTITY_REGEX = re.compile(r"&(?:#\d+|#[xX][0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*);")
ELEMENT_REGEX = re.compile(r"<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9-]*)[^>]*?(/?)\s*>")
# Elements that never carry a closing tag, so an open one is not "unclosed".
VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    },
)


@dataclass
class FeedParserConfig:
    """Everything the parser needs to turn feed content into sensor data."""

    feed_url: str
    date_format: str
    show_topn: int
    remove_summary_image: bool = False
    local_time: bool = False
    # Characters of text kept per value; NO_TEXT_LIMIT keeps everything.
    max_text_length: int = DEFAULT_MAX_TEXT_LENGTH
    inclusions: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    name: str = ""


@dataclass
class ParsedFeed:
    """Result of parsing a feed."""

    channel: dict[str, Any] = field(default_factory=dict)
    entries: list[dict[str, Any]] = field(default_factory=list)
    native_value: int | None = None


def parse_feed(content: bytes | str, config: FeedParserConfig) -> ParsedFeed:
    """Parse raw feed content into channel info and entries."""
    parsed_feed: FeedParserDict = feedparser.parse(content)

    if not parsed_feed.feed:
        _LOGGER.warning("Feed %s: No data received.", config.name)
        return ParsedFeed(native_value=None)

    channel = generate_channel_info(parsed_feed.feed, config)

    if not parsed_feed.entries:
        _LOGGER.warning("Feed %s: No entries found.", config.name)
        return ParsedFeed(channel=channel, native_value=0)

    _LOGGER.debug("Feed %s: Feed data fetched successfully", config.name)
    # The sensor value is the number of entries, capped at show_topn. A negative
    # cap would slice from the end of the list (`entries[:-5]` keeps all but the
    # last five) and put a negative number in the state, so treat anything below
    # zero as zero.
    considered = min(len(parsed_feed.entries), max(config.show_topn, 0))
    _LOGGER.debug(
        "Feed %s: %s entries is going to be added to the sensor",
        config.name,
        considered,
    )
    # An entry can come out with nothing in it - narrow `inclusions` and a value
    # the entry does not have, or a date no parser could read - and a keyless
    # entry is something a card has to render around. It is left out, and the
    # state counts what is actually there, which is what the state has always
    # meant.
    entries = [
        entry
        for feed_entry in parsed_feed.entries[:considered]
        if (entry := generate_sensor_entry(feed_entry, config))
    ]
    if dropped := considered - len(entries):
        _LOGGER.debug(
            "Feed %s: %s of %s entries had no value left after filtering and "
            "are not exposed",
            config.name,
            dropped,
            considered,
        )
    _LOGGER.debug(
        "Feed %s: Sensor state updated - %s entries",
        config.name,
        len(entries),
    )
    _warn_if_oversized(channel, entries, config)
    return ParsedFeed(channel=channel, entries=entries, native_value=len(entries))


def is_parsable_feed(content: bytes | str) -> bool:
    """Return whether `content` actually is an RSS/Atom feed.

    A reachable URL is not a feed URL. Pointed at an ordinary web page,
    feedparser returns a result with an empty `version` and no entries instead
    of raising, which used to give a config entry whose sensor sits at 0 and
    logs "No entries found" on every poll. The `version` is what feedparser
    derives from the root element (`rss20`, `atom10`, ...), so it is the field
    that tells a feed from a page; entries are accepted as well for the rare
    feed whose flavour it cannot name.
    """
    parsed: FeedParserDict = feedparser.parse(content)
    return bool(parsed.get("version") or parsed.get("entries"))


def _cut_index(value: str, limit: int) -> int:
    """Return where `value` may be cut without splitting a tag or an entity.

    Tags and entities are looked at in the order they appear in the value.
    Iterating over the two match sets one after the other instead would let a
    tag positioned behind the cut end the scan before a single entity was
    examined, and `&nbsp;` would be cut into `&nbsp`.
    """
    cut = limit
    matches = sorted(
        (*TAG_REGEX.finditer(value), *ENTITY_REGEX.finditer(value)),
        key=lambda match: match.start(),
    )
    for match in matches:
        start, end = match.span()
        if start >= cut:
            break
        if start < cut < end:
            cut = start
    return cut


def _unclosed_elements(fragment: str) -> list[str]:
    """Return the still open elements of an HTML fragment, outermost first."""
    stack: list[str] = []
    for match in ELEMENT_REGEX.finditer(fragment):
        closing, name, self_closing = (
            match.group(1),
            match.group(2).lower(),
            match.group(3),
        )
        if closing:
            # The innermost open element of that name is the one being closed.
            # Looking up the outermost instead would pop an outer twin along
            # with it, so `<div>a<div>b</div>` would count as fully closed.
            if name in stack:
                del stack[len(stack) - 1 - stack[::-1].index(name) :]
        elif not self_closing and name not in VOID_ELEMENTS:
            stack.append(name)
    return stack


def _without_unfittable_tags(value: str, max_length: int) -> str:
    """Drop the tags that are longer than everything the value may keep.

    A summary can open with an `<img src="data:image/png;base64,...">` that is
    kilobytes long on its own. Such a tag can never be part of a shortened
    value, and refusing to split it would collapse the cut to zero and throw
    the whole summary away - text included. Removing it keeps the words, which
    is what the value is read for; the markup around it stays untouched.
    """
    return TAG_REGEX.sub(
        lambda match: "" if len(match.group()) > max_length else match.group(),
        value,
    )


def _shorten_text(value: str, max_length: int) -> str:
    """Shorten a single string without ever leaving broken markup behind.

    `summary` and `content.value` routinely carry HTML, so slicing the raw
    string at a character offset can end inside a tag or a character entity -
    `...<a href="https://exam`. Cutting at a tag boundary instead is what is
    done here, rather than stripping the markup first: the markup is part of
    what these values are for. The feed's own image lives inside the summary
    and the `remove_summary_image` option exists precisely so a user can decide
    whether to keep it, which stripping would decide for them. Whatever is
    still open at the cut is closed again, so the result is a whole fragment.
    """
    if len(value) <= max_length:
        return value
    value = _without_unfittable_tags(value, max_length)
    if len(value) <= max_length:
        return value
    budget = max_length
    while budget > 0:
        fragment = value[: _cut_index(value, budget)].rstrip()
        closing = "".join(
            f"</{name}>" for name in reversed(_unclosed_elements(fragment))
        )
        shortened = fragment + TRUNCATION_SUFFIX + closing
        overflow = len(shortened) - (max_length + len(TRUNCATION_SUFFIX))
        if overflow <= 0:
            return shortened
        # The closing tags count against the budget too, so make room for them.
        budget -= overflow
    return TRUNCATION_SUFFIX


def _truncate(value: object, max_length: int) -> object:
    """Shorten long text so a feed cannot blow up the state attributes.

    Whole articles regularly arrive in `summary` or `content`; keeping them in
    full is what pushes the attribute payload past the recorder's limit.
    """
    if isinstance(value, str):
        return _shorten_text(value, max_length)
    if isinstance(value, list):
        return [_truncate(item, max_length) for item in value]
    if isinstance(value, dict):
        return {
            key: item if key in UNTRUNCATED_KEYS else _truncate(item, max_length)
            for key, item in value.items()
        }
    return value


def _truncate_entry(entry: dict[str, Any], config: FeedParserConfig) -> dict[str, Any]:
    """Return a copy of an entry with its long text values shortened."""
    max_length = config.max_text_length
    if max_length <= NO_TEXT_LIMIT:
        return entry
    return {
        key: value if key in UNTRUNCATED_KEYS else _truncate(value, max_length)
        for key, value in entry.items()
    }


def _warn_if_oversized(
    channel: dict[str, Any],
    entries: list[dict[str, Any]],
    config: FeedParserConfig,
) -> None:
    """Warn when the state attributes are too large for the recorder.

    Nothing breaks visibly when they are - the state still shows up in the UI,
    the recorder simply drops its attributes - so without this a user who
    raised show_topn on a verbose feed has no way of learning why the history
    of that sensor is empty.

    The feed is polled on a timer, so warning on every poll would repeat the
    same line for as long as the feed is configured. It is logged once per
    configuration instead, and again once the settings it names have changed
    or the attributes fit and grow past the limit anew.
    """
    attributes = {"channel": channel, "entries": entries}
    size = len(json.dumps(attributes, default=str).encode())
    feed_key = config.feed_url or config.name
    settings = (config.show_topn, config.max_text_length)
    if size > MAX_STATE_ATTRS_BYTES:
        if _OVERSIZED_WARNED.get(feed_key) == settings:
            return
        _OVERSIZED_WARNED[feed_key] = settings
        _LOGGER.warning(
            (
                "Feed %s: the state attributes are %s bytes, which is more than "
                "the %s bytes Home Assistant's recorder stores - the history of "
                "this sensor will have no attributes. Lower show_topn (now %s) "
                "or max_text_length (now %s), or narrow down inclusions."
            ),
            config.name,
            size,
            MAX_STATE_ATTRS_BYTES,
            config.show_topn,
            config.max_text_length,
        )
    else:
        # It fits again - a later regression is worth hearing about.
        _OVERSIZED_WARNED.pop(feed_key, None)


def _resolve_url(url: str | None, config: FeedParserConfig) -> str:
    """Resolve a feed URL against the feed and drop it if it is not one.

    `link`, `image` and `audio` are rendered as an `href` or a `src`, so a
    `javascript:` or `data:` URL in one of them is the same hole as a script in
    the summary. The check runs before the value is joined with the feed URL:
    joining turns anything the scheme allow-list would reject into a relative
    path under the feed's host, which hides the value the feed actually sent.
    """
    if not url:
        return ""
    safe = safe_url(url)
    if not safe:
        return ""
    return urljoin(config.feed_url, safe)


# Flat dispatch over the keys a feed entry can carry: the branch count is the
# shape of the data, not tangled control flow. Splitting it is worth doing on
# its own, away from a QA round that must not move the parser's behaviour.
def generate_sensor_entry(  # noqa: C901
    feed_entry: FeedParserDict,
    config: FeedParserConfig,
) -> dict[str, Any]:
    """Turn a single feed entry into the dict stored on the sensor."""
    _LOGGER.debug("Feed %s: Generating sensor entry for %s", config.name, feed_entry)
    sensor_entry: dict[str, Any] = {}
    for key, value in feed_entry.items():
        if _is_filtered(key, config):
            continue
        if key in DATE_KEYS:
            parsed_date = parse_date(value, config)
            if parsed_date is None:
                continue
            sensor_entry[key] = parsed_date.strftime(config.date_format)
        elif key == "image":
            if resolved := _resolve_url(value.get("href"), config):
                sensor_entry["image"] = resolved
        elif isinstance(value, dict | list | str | int | float | bool):
            sensor_entry[key] = value

    # `image`, `audio` and `link` are derived rather than copied, so they have
    # to go through the same filter as every other key. Checking the exclusions
    # alone put them back into an entry that `inclusions` had just narrowed
    # down to something else, which is not what the option says it does.
    if (
        not _is_filtered("image", config)
        and "image" not in sensor_entry
        and (image := _resolve_url(process_image(feed_entry, config), config))
    ):
        sensor_entry["image"] = image
    if (
        not _is_filtered("audio", config)
        and "audio" not in sensor_entry
        and (audio := _resolve_url(process_audio(feed_entry, config), config))
    ):
        sensor_entry["audio"] = audio
    if (
        not _is_filtered("link", config)
        and "link" not in sensor_entry
        and (processed_link := _resolve_url(process_link(feed_entry, config), config))
    ):
        sensor_entry["link"] = processed_link
    # Before `remove_summary_image` and the truncation, so both work on the
    # markup the sensor actually exposes rather than on what the feed sent.
    sensor_entry = sanitize_mapping(sensor_entry)
    if config.remove_summary_image and "summary" in sensor_entry:
        sensor_entry["summary"] = re.sub(IMAGE_REGEX, "", sensor_entry["summary"])
    sensor_entry = _truncate_entry(sensor_entry, config)
    _LOGGER.debug("Feed %s: Generated sensor entry: %s", config.name, sensor_entry)
    return sensor_entry


def generate_channel_info(
    feed_info: FeedParserDict,
    config: FeedParserConfig,
) -> dict[str, Any]:
    """Build the `channel` attribute from the feed-level metadata."""
    _LOGGER.debug("Feed %s: Generating channel info for %s", config.name, feed_info)
    channel_info: dict[str, Any] = {}
    for key, value in feed_info.items():
        if _is_filtered(key, config) or key == "image":
            continue
        if key in DATE_KEYS:
            parsed_channel_date = parse_date(value, config)
            if parsed_channel_date is None:
                continue
            channel_info[key] = parsed_channel_date.strftime(config.date_format)
        elif isinstance(value, dict | list | str | int | float | bool):
            channel_info[key] = value

    if not _is_filtered("image", config):
        image_url = feed_info.get("image", {}).get("href") or feed_info.get(
            "image",
            {},
        ).get("url")
        if not image_url and feed_info.get("logo"):
            image_url = feed_info.logo
        if resolved := _resolve_url(image_url, config):
            channel_info["image"] = resolved
    channel_info = sanitize_mapping(channel_info)
    channel_info = _truncate_entry(channel_info, config)
    _LOGGER.debug("Feed %s: Generated channel info: %s", config.name, channel_info)
    return channel_info


def _is_filtered(key: str, config: FeedParserConfig) -> bool:
    """Return whether a feed key should be skipped entirely."""
    return bool(
        (config.inclusions and key not in config.inclusions)
        or ("parsed" in key)
        or (key.endswith("_detail") or key == "detail")
        or (key in config.exclusions),
    )


def parse_date(date: object, config: FeedParserConfig) -> datetime | None:
    """Parse a feed date, falling back to dateutil. None when unparsable.

    Substituting the current time for a date nobody could read used to make the
    entry look like it had just been published, and it moved on every poll -
    a date that is wrong in a way no consumer can detect. An entry with no
    usable date simply has no date; the key is left out, which is already what
    happens for a feed that does not send one.

    Unparsable covers whatever a feed puts under a date key, not only a string
    neither parser understands: a feed that sends a number or a list there used
    to take the whole poll down with an AttributeError out of dateutil.
    """
    if not isinstance(date, str):
        _LOGGER.warning(
            "Feed %s: The date %r is not text and cannot be parsed. "
            "The entry is kept without it.",
            config.name,
            date,
        )
        return None
    try:
        parsed_time: datetime = email.utils.parsedate_to_datetime(date)
    except (ValueError, TypeError):
        _LOGGER.debug(
            (
                "Feed %s: Unable to parse RFC-822 date from '%s'. This could be "
                "caused by an incorrect pubDate format in the RSS feed. "
                "Trying to use dateutil."
            ),
            config.name,
            date,
        )
        try:
            parsed_time = dateutil_parser.parse(date)
        except (dateutil_parser.ParserError, TypeError, OverflowError) as e:
            _LOGGER.warning(
                "Feed %s: Unable to parse date '%s' with dateutil: %s. "
                "The entry is kept without it.",
                config.name,
                date,
                e,
            )
            return None

    if not parsed_time.tzinfo:
        _LOGGER.debug(
            "Feed %s: No timezone info found in date '%s'. Assuming UTC.",
            config.name,
            date,
        )
        parsed_time = parsed_time.replace(tzinfo=UTC)
    if not parsed_time.tzname():
        # A named offset is what strftime needs. `timezone()` refuses one of a
        # day or more, which a feed can send - `+9999` parses fine and only
        # blows up here - so an entry with such an offset has no usable date
        # rather than taking the poll down with it.
        try:
            parsed_time = parsed_time.replace(
                tzinfo=timezone(parsed_time.utcoffset()),  # type: ignore[arg-type]
            )
        except ValueError as e:
            _LOGGER.warning(
                "Feed %s: The date '%s' has a timezone offset of a day or "
                "more: %s. The entry is kept without it.",
                config.name,
                date,
                e,
            )
            return None

    if config.local_time:
        parsed_time = dt.as_local(parsed_time)
    else:
        parsed_time = dt.as_utc(parsed_time)
    _LOGGER.debug("Feed %s: Parsed date: %s", config.name, parsed_time)
    return parsed_time


# Four independent places a feed can put an image, tried in order of how much
# the feed tells us about them. Same reasoning as `generate_sensor_entry`.
def process_image(  # noqa: C901
    feed_entry: FeedParserDict,
    config: FeedParserConfig,
) -> str | None:
    """Return the image URL for a feed entry, if one can be found."""
    if feed_entry.get("media_content"):
        for item in feed_entry["media_content"]:
            if item.get("url") and (
                item.get("medium") == "image"
                or (item.get("type") or "").startswith("image/")
            ):
                return item.get("url")
    if feed_entry.get("media_thumbnail"):
        for item in feed_entry["media_thumbnail"]:
            if item.get("url"):
                return item.get("url")
    if feed_entry.get("enclosures"):
        for enc in feed_entry["enclosures"]:
            url = enc.get("href") or enc.get("url")
            if url and (enc.get("type") or "").startswith("image/"):
                return url
    if "summary" in feed_entry:
        images = re.findall(IMAGE_REGEX, feed_entry["summary"], re.S)
        if images:
            return images[0]
    _LOGGER.debug(
        "Feed %s: Image is in inclusions, but no image was found for %s",
        config.name,
        feed_entry,
    )
    return None


def process_audio(
    feed_entry: FeedParserDict,
    config: FeedParserConfig,
) -> str | None:
    """Return the audio URL for a feed entry, if one can be found."""
    if feed_entry.get("media_content"):
        for item in feed_entry["media_content"]:
            if item.get("url") and (item.get("type") or "").startswith("audio/"):
                return item.get("url")
    if feed_entry.get("enclosures"):
        for enc in feed_entry["enclosures"]:
            url = enc.get("href") or enc.get("url")
            if url and (enc.get("type") or "").startswith("audio/"):
                return url
    _LOGGER.debug(
        "Feed %s: Image or audio processed, but none found for %s",
        config.name,
        feed_entry.get("title"),
    )
    return None


def process_link(feed_entry: FeedParserDict, config: FeedParserConfig) -> str:
    """Return the link for a feed entry."""
    if "links" in feed_entry:
        if len(feed_entry["links"]) > 1:
            _LOGGER.debug(
                "Feed %s: More than one link found for %s. Using the first link.",
                config.name,
                feed_entry,
            )
        return feed_entry["links"][0]["href"]
    return ""
