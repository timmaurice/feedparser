"""Parsing helpers for RSS/Atom feed content.

This module is intentionally free of network and config-entry concerns so it can
be exercised directly by the test suite against the fixtures in `tests/data`.
"""

from __future__ import annotations

import email.utils
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import feedparser  # type: ignore[import]
from dateutil import parser as dateutil_parser
from feedparser import FeedParserDict
from homeassistant.util import dt

from .const import IMAGE_REGEX

_LOGGER: logging.Logger = logging.getLogger(__name__)

DATE_KEYS = ("published", "updated", "created", "expired")


@dataclass
class FeedParserConfig:
    """Everything the parser needs to turn feed content into sensor data."""

    feed_url: str
    date_format: str
    show_topn: int
    remove_summary_image: bool = False
    local_time: bool = False
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
    # the sensor value is the number of entries, capped at show_topn
    native_value = min(len(parsed_feed.entries), config.show_topn)
    _LOGGER.debug(
        "Feed %s: %s entries is going to be added to the sensor",
        config.name,
        native_value,
    )
    entries = [
        generate_sensor_entry(feed_entry, config)
        for feed_entry in parsed_feed.entries[:native_value]
    ]
    _LOGGER.debug(
        "Feed %s: Sensor state updated - %s entries",
        config.name,
        len(entries),
    )
    return ParsedFeed(channel=channel, entries=entries, native_value=native_value)


def generate_sensor_entry(
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
            parsed_date: datetime = parse_date(value, config)
            sensor_entry[key] = parsed_date.strftime(config.date_format)
        elif key == "image":
            if href := value.get("href"):
                sensor_entry["image"] = urljoin(config.feed_url, href)
        elif isinstance(value, (dict, list, str, int, float, bool)):
            sensor_entry[key] = value

    if (
        "image" not in config.exclusions
        and "image" not in sensor_entry
        and (image := process_image(feed_entry, config))
    ):
        sensor_entry["image"] = urljoin(config.feed_url, image)
    if (
        "audio" not in config.exclusions
        and "audio" not in sensor_entry
        and (audio := process_audio(feed_entry, config))
    ):
        sensor_entry["audio"] = audio
    if (
        "link" not in config.exclusions
        and "link" not in sensor_entry
        and (processed_link := process_link(feed_entry, config))
    ):
        sensor_entry["link"] = processed_link
    if config.remove_summary_image and "summary" in sensor_entry:
        sensor_entry["summary"] = re.sub(IMAGE_REGEX, "", sensor_entry["summary"])
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
            parsed_date: datetime = parse_date(value, config)
            channel_info[key] = parsed_date.strftime(config.date_format)
        elif isinstance(value, (dict, list, str, int, float, bool)):
            channel_info[key] = value

    if "image" not in config.exclusions:
        image_url = feed_info.get("image", {}).get("href") or feed_info.get(
            "image",
            {},
        ).get("url")
        if not image_url and feed_info.get("logo"):
            image_url = feed_info.logo
        if image_url:
            channel_info["image"] = urljoin(config.feed_url, image_url)
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


def parse_date(date: str, config: FeedParserConfig) -> datetime:
    """Parse a feed date, falling back to dateutil and finally to now."""
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
        except (dateutil_parser.ParserError, TypeError) as e:
            _LOGGER.warning(
                "Feed %s: Unable to parse date '%s' with dateutil: %s. "
                "Using current time as fallback.",
                config.name,
                date,
                e,
            )
            parsed_time = dt.utcnow()

    if not parsed_time.tzinfo:
        _LOGGER.debug(
            "Feed %s: No timezone info found in date '%s'. Assuming UTC.",
            config.name,
            date,
        )
        parsed_time = parsed_time.replace(tzinfo=timezone.utc)
    if not parsed_time.tzname():
        parsed_time = parsed_time.replace(
            tzinfo=timezone(parsed_time.utcoffset()),  # type: ignore[arg-type]
        )

    if config.local_time:
        parsed_time = dt.as_local(parsed_time)
    else:
        parsed_time = dt.as_utc(parsed_time)
    _LOGGER.debug("Feed %s: Parsed date: %s", config.name, parsed_time)
    return parsed_time


def process_image(
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
