"""Tests the feedparser parsing layer."""

from __future__ import annotations

import logging
import re
from contextlib import nullcontext, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import feedparser
import pytest
from conftest import local_feed_config, parse_local_feed
from constants import DATE_FORMAT

from custom_components.feedparser.const import (
    DEFAULT_MAX_TEXT_LENGTH,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DEFAULT_TOPN,
    IMAGE_REGEX,
    MAX_SCAN_INTERVAL_MINUTES,
    MAX_STATE_ATTRS_BYTES,
    MIN_SCAN_INTERVAL_MINUTES,
    NO_TEXT_LIMIT,
    TRUNCATION_SUFFIX,
    UNTRUNCATED_KEYS,
    scan_interval_from_minutes,
)
from custom_components.feedparser.parser import (
    _OVERSIZED_WARNED,
    FeedParserConfig,
    ParsedFeed,
    parse_date,
    parse_feed,
)

if TYPE_CHECKING:
    import time

    from feedsource import FeedSource


@pytest.fixture(autouse=True)
def _forget_oversize_warnings() -> None:
    """Let every test start out as a feed that has not warned yet."""
    _OVERSIZED_WARNED.clear()


def test_simple(parsed_feed: ParsedFeed) -> None:
    """Test simple."""
    assert parsed_feed.entries


def test_parse_feed(feed: FeedSource) -> None:
    """Test parsing a feed with its own configuration."""
    parsed = parse_local_feed(feed)
    assert parsed.entries

    # assert that the sensor value is equal to the number of entries
    assert parsed.native_value == len(parsed.entries)

    # assert that all entries have a title
    assert all(e["title"] for e in parsed.entries)

    # assert that all entries have a link
    assert all(e["link"] for e in parsed.entries)

    # assert that all entries have a published date
    assert all(e["published"] for e in parsed.entries)

    # assert that all entries have non-default image
    if feed.all_entries_have_images and "image" in feed.sensor_config.inclusions:
        if feed.has_images:
            assert all(
                "image" in e for e in parsed.entries
            ), "Image missing for entry that should have an image"
        else:
            assert all(
                "image" not in e for e in parsed.entries
            ), "Image found for entry that should not have an image"

    # assert that all entries have a unique link
    if feed.has_unique_links:
        assert len({e["link"] for e in parsed.entries}) == len(
            parsed.entries,
        ), "Duplicate links found"

    # assert that all entries have a unique title
    if feed.has_unique_titles:
        assert len({e["title"] for e in parsed.entries}) == len(
            parsed.entries,
        ), "Duplicate titles found"

    # assert that all entries have a unique published date
    if feed.has_unique_dates:
        assert len({e["published"] for e in parsed.entries}) == len(
            parsed.entries,
        ), "Duplicate published dates found"

    # assert that all entries have a unique image
    if feed.has_images and feed.has_unique_images:
        images = [e["image"] for e in parsed.entries if "image" in e]
        assert len(set(images)) == len(images), "Duplicate images found"

    # assert that the feed has audio
    if feed.has_audio:
        assert any(
            "audio" in e for e in parsed.entries
        ), "Audio missing for feed that should have audio"


ZEIT_VERBRECHEN = Path(__file__).parent / "data/zeit_verbrechen.xml"
# What the numbers below are pinned to, spelled out once and on purpose: these
# are the counts the integration must produce, not whatever the constants say.
EXPECTED_DEFAULT_ENTRIES = 5
EXPECTED_OVERRIDE_ENTRIES = 50


def zeit_verbrechen_config(**overrides: object) -> FeedParserConfig:
    """Return a config for the zeit_verbrechen fixture, 259 entries long."""
    defaults: dict[str, object] = {
        "feed_url": ZEIT_VERBRECHEN.absolute().as_uri(),
        "name": "zeit_verbrechen",
        "date_format": DATE_FORMAT,
        "show_topn": DEFAULT_TOPN,
    }
    return FeedParserConfig(**(defaults | overrides))  # type: ignore[arg-type]


def test_default_topn_caps_entries() -> None:
    """Test that the default keeps the newest five entries and no more."""
    # 259 entries in the fixture, five of them survive the default
    parsed = parse_feed(ZEIT_VERBRECHEN.read_bytes(), zeit_verbrechen_config())
    assert DEFAULT_TOPN == EXPECTED_DEFAULT_ENTRIES
    assert len(parsed.entries) == EXPECTED_DEFAULT_ENTRIES
    assert parsed.native_value == EXPECTED_DEFAULT_ENTRIES

    newest = feedparser.parse(ZEIT_VERBRECHEN).entries[:EXPECTED_DEFAULT_ENTRIES]
    assert [e["title"] for e in parsed.entries] == [e.title for e in newest]


def test_show_topn_still_overrides_the_default() -> None:
    """Test that a user asking for more entries still gets exactly that many."""
    parsed = parse_feed(
        ZEIT_VERBRECHEN.read_bytes(),
        zeit_verbrechen_config(show_topn=EXPECTED_OVERRIDE_ENTRIES),
    )
    assert len(parsed.entries) == EXPECTED_OVERRIDE_ENTRIES
    assert parsed.native_value == EXPECTED_OVERRIDE_ENTRIES


# Variants of one `<img>` that the regex has to see. feedparser normalises the
# markup it keeps, which is why these are pinned against the pattern itself
# rather than through a feed: the parsed summary would never show them, and the
# same pattern is used on `content` values and by `process_image`.
IMG_VARIANTS = [
    '<img src="a.png" alt="x">',
    "<img src='a.png' alt='x'>",
    '<img alt="x" src="a.png">',
    '<img\n  src="a.png"\n  alt="x">',
]


@pytest.mark.parametrize("markup", IMG_VARIANTS)
def test_the_image_pattern_matches_the_usual_img_spellings(markup: str) -> None:
    """Test the pattern behind `remove_summary_image` and the image fallback.

    It only matched a double quoted `src` on a single line, so a single quoted
    or wrapped tag was silently left in the summary and its URL was not found.
    """
    assert re.sub(IMAGE_REGEX, "", markup) == ""
    assert re.findall(IMAGE_REGEX, markup, re.S) == ["a.png"]


SINGLE_QUOTED_IMAGE = "https://ex.com/a.png"
# An Atom summary the feed declares as text: feedparser unescapes it and hands
# it over without normalising the markup, so the single quotes reach the regex
# exactly as the publisher wrote them.
FEED_WITH_A_SINGLE_QUOTED_IMAGE = f"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Single quoted</title>
  <entry>
    <title>Has an image</title>
    <summary type="text">
      &lt;p&gt;Text.&lt;img src='{SINGLE_QUOTED_IMAGE}' alt='x'&gt;&lt;/p&gt;
    </summary>
  </entry>
</feed>
"""


def test_a_single_quoted_image_is_found_and_removed() -> None:
    """Test the image pattern through a feed, not only against itself.

    The pattern was pinned at pattern level on the assumption that feedparser
    normalises every summary the regex ever sees. It does not: a value the feed
    declares as text is passed through as written, so a publisher's single
    quoted `<img>` was neither found by the image fallback nor removed by
    `remove_summary_image`.
    """
    config = FeedParserConfig(
        feed_url="https://ex.com/feed.xml",
        name="single",
        date_format=DATE_FORMAT,
        show_topn=1,
        remove_summary_image=True,
        max_text_length=NO_TEXT_LIMIT,
    )
    entry = parse_feed(FEED_WITH_A_SINGLE_QUOTED_IMAGE, config).entries[0]
    assert entry["image"] == SINGLE_QUOTED_IMAGE
    assert "<img" not in entry["summary"]
    assert "Text." in entry["summary"]


UNPARSABLE_DATE = "not a date at all"
FEED_WITH_A_BROKEN_DATE = f"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Broken dates</title>
  <item><title>No usable date</title><pubDate>{UNPARSABLE_DATE}</pubDate></item>
  <item><title>Proper date</title>
    <pubDate>Tue, 13 Jan 2026 21:06:00 +0000</pubDate></item>
</channel></rss>
"""


def test_an_unparsable_date_is_left_out(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that a date nobody can read does not become the current time.

    The fallback used to be `now()`, so the entry claimed to have just been
    published and said so again with a new time on every poll - wrong in a way
    no consumer of the sensor can spot.
    """
    with caplog.at_level(logging.WARNING):
        parsed = parse_feed(
            FEED_WITH_A_BROKEN_DATE,
            zeit_verbrechen_config(),
        )
    broken, fine = parsed.entries
    assert "published" not in broken
    assert broken["title"] == "No usable date"
    assert "published" in fine
    assert UNPARSABLE_DATE in caplog.text


FEED_WITH_A_HUGE_OFFSET = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Impossible offsets</title>
  <item><title>Off the map</title>
    <pubDate>Tue, 13 Jan 2026 21:06:00 +9999</pubDate></item>
  <item><title>Proper date</title>
    <pubDate>Tue, 13 Jan 2026 21:06:00 +0000</pubDate></item>
</channel></rss>
"""


def test_a_timezone_offset_of_a_day_or_more_does_not_break_the_poll() -> None:
    """Test that an impossible offset costs the date, not the whole feed.

    `+9999` parses fine and only fails when the offset is turned into a named
    timezone, which raised out of `parse_date` and took the poll down with it.
    """
    parsed = parse_feed(FEED_WITH_A_HUGE_OFFSET, zeit_verbrechen_config())
    broken, fine = parsed.entries
    assert "published" not in broken
    assert broken["title"] == "Off the map"
    assert "published" in fine


@pytest.mark.parametrize("value", [12345, ["a date"], {"a": 1}, 1.5])
def test_a_date_that_is_not_text_is_dropped(value: object) -> None:
    """Test that a feed cannot take a poll down by sending a non-string date.

    Only `ParserError`, `TypeError` and `OverflowError` were caught, and
    dateutil answers a value it cannot even read with an `AttributeError`.
    """
    assert parse_date(value, zeit_verbrechen_config()) is None


def test_an_entry_with_nothing_left_in_it_is_not_exposed() -> None:
    """Test that a card never gets a keyless entry, and the state agrees.

    `inclusions` narrowed to a single key plus a date no parser can read leaves
    an entry with no keys at all. It used to be exposed as `{}` and counted in
    the state, so the sensor claimed an entry a card could render nothing of.
    """
    parsed = parse_feed(
        FEED_WITH_A_BROKEN_DATE,
        zeit_verbrechen_config(inclusions=["published"]),
    )
    assert parsed.entries == [{"published": parsed.entries[0]["published"]}]
    assert parsed.native_value == len(parsed.entries) == 1


# The fixture carries an audio enclosure and a link on every entry, which is
# what makes it the one to pin the derived keys against.
DERIVED_KEYS = ("image", "audio", "link")


def test_inclusions_also_narrow_down_the_derived_keys() -> None:
    """Test that `link`, `audio` and `image` obey `inclusions` like any key.

    They are derived from the feed entry instead of copied out of it, and used
    to be gated on the exclusions alone - so an entry narrowed down to
    `title, published` came back carrying `audio` and `link` as well.
    """
    parsed = parse_feed(
        ZEIT_VERBRECHEN.read_bytes(),
        zeit_verbrechen_config(inclusions=["title", "published"]),
    )
    assert parsed.entries
    for entry in parsed.entries:
        assert set(entry) == {"title", "published"}


def test_a_derived_key_that_is_included_is_still_added() -> None:
    """Test that naming a derived key in `inclusions` is what gets it added."""
    parsed = parse_feed(
        ZEIT_VERBRECHEN.read_bytes(),
        zeit_verbrechen_config(inclusions=["title", *DERIVED_KEYS]),
    )
    assert parsed.entries
    for entry in parsed.entries:
        assert "title" in entry
        assert {"audio", "link"} <= set(entry)
        assert set(entry) <= {"title", *DERIVED_KEYS}


def test_exclusions_still_drop_a_derived_key_on_their_own() -> None:
    """Test that excluding a derived key without any inclusions still works."""
    parsed = parse_feed(
        ZEIT_VERBRECHEN.read_bytes(),
        zeit_verbrechen_config(exclusions=list(DERIVED_KEYS)),
    )
    assert parsed.entries
    for entry in parsed.entries:
        assert not set(entry) & set(DERIVED_KEYS)


def test_inclusions_narrow_down_the_channel_image_too() -> None:
    """Test that the feed level image follows the same rule as the entries."""
    included = parse_feed(
        ZEIT_VERBRECHEN.read_bytes(),
        zeit_verbrechen_config(inclusions=["title", "image"]),
    )
    assert "image" in included.channel
    narrowed = parse_feed(
        ZEIT_VERBRECHEN.read_bytes(),
        zeit_verbrechen_config(inclusions=["title"]),
    )
    assert "image" not in narrowed.channel


@pytest.mark.parametrize("show_topn", [0, -5])
def test_a_show_topn_below_one_yields_no_entries(show_topn: int) -> None:
    """Test that a non-positive cap cannot produce a negative state.

    A YAML sensor may set 0, and an entry written before the UI validated the
    field can still carry a negative number. `entries[:-5]` keeps all but the
    last five, so -5 used to give a sensor whose state was -5 while it carried
    254 entries.
    """
    parsed = parse_feed(
        ZEIT_VERBRECHEN.read_bytes(),
        zeit_verbrechen_config(show_topn=show_topn),
    )
    assert parsed.native_value == 0
    assert parsed.entries == []


def _text_values(value: object) -> list[str]:
    """Return every string in a parsed entry that is not a URL or an id."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in _text_values(item)]
    if isinstance(value, dict):
        return [
            text
            for key, item in value.items()
            if key not in UNTRUNCATED_KEYS
            for text in _text_values(item)
        ]
    return []


def test_long_entry_text_is_truncated() -> None:
    """Test that whole articles are cut down before they reach the sensor."""
    parsed = parse_feed(ZEIT_VERBRECHEN.read_bytes(), zeit_verbrechen_config())
    assert parsed.entries

    max_length = DEFAULT_MAX_TEXT_LENGTH + len(TRUNCATION_SUFFIX)
    texts = [
        text
        for entry in parsed.entries
        for key, value in entry.items()
        if key not in UNTRUNCATED_KEYS
        for text in _text_values(value)
    ]
    assert all(len(text) <= max_length for text in texts)
    assert any(
        TRUNCATION_SUFFIX in text for text in texts
    ), "This fixture is expected to carry text long enough to be truncated"

    # links are URLs, cutting them would only break them
    assert all("://" in e["link"] for e in parsed.entries)


HTML_FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>html</title>
<item>
  <title>Broken markup</title>
  <link>https://example.com/article</link>
  <pubDate>Tue, 05 Mar 2024 09:00:00 +0000</pubDate>
  <description>{summary}</description>
</item>
</channel></rss>"""


def html_feed(summary: str) -> bytes:
    """Return a one item feed whose summary is the given markup."""
    return HTML_FEED.format(summary=summary).encode()


def html_feed_config(**overrides: object) -> FeedParserConfig:
    """Return a config for the synthetic HTML feed."""
    defaults: dict[str, object] = {
        "feed_url": "https://example.com/feed",
        "name": "html",
        "date_format": DATE_FORMAT,
        "show_topn": DEFAULT_TOPN,
    }
    return FeedParserConfig(**(defaults | overrides))  # type: ignore[arg-type]


def open_elements(fragment: str) -> list[str]:
    """Return the elements left open in a fragment - a naive re-implementation."""
    stack: list[str] = []
    elements = re.findall(r"<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9-]*)[^>]*>", fragment)
    for closing, name in elements:
        if closing:
            assert stack, f"stray </{name}>"
            assert stack[-1] == name.lower(), f"stray </{name}>"
            stack.pop()
        elif name.lower() not in {"img", "br", "hr"}:
            stack.append(name.lower())
    return stack


def test_truncation_does_not_cut_html_apart() -> None:
    """Test that a truncated summary is never a half written tag."""
    # the anchor opens a few characters before the cut, so slicing the raw
    # string at DEFAULT_MAX_TEXT_LENGTH would end inside its href
    summary = (
        "<p>"
        + "word " * 45
        + '<a href="https://example.com/a-very-long-target-url">linked words</a>'
        + " and a tail long enough to be dropped " * 5
        + "</p>"
    )
    assert len(summary) > DEFAULT_MAX_TEXT_LENGTH
    assert summary.index("<a href") < DEFAULT_MAX_TEXT_LENGTH
    assert summary.index("</a>") > DEFAULT_MAX_TEXT_LENGTH

    truncated = parse_feed(html_feed(summary), html_feed_config()).entries[0]["summary"]

    assert TRUNCATION_SUFFIX in truncated
    assert len(truncated) <= DEFAULT_MAX_TEXT_LENGTH + len(TRUNCATION_SUFFIX)
    # nothing of the anchor is left, and above all no fragment of its tag
    assert "href" not in truncated
    assert truncated.count("<") == truncated.count(">")
    assert open_elements(truncated) == [], "the fragment leaves an element open"
    assert truncated.startswith("<p>")
    assert truncated.endswith(TRUNCATION_SUFFIX + "</p>")


def test_truncation_closes_what_it_leaves_open() -> None:
    """Test that markup that was still open at the cut is closed again."""
    summary = "<p><strong>" + "word " * 100 + "</strong></p>"
    truncated = parse_feed(html_feed(summary), html_feed_config()).entries[0]["summary"]
    assert truncated.endswith(TRUNCATION_SUFFIX + "</strong></p>")
    assert open_elements(truncated) == []


def test_plain_text_is_cut_at_the_configured_length() -> None:
    """Test that text without markup is cut exactly at the limit."""
    summary = "abcdefghij" * 100
    truncated = parse_feed(html_feed(summary), html_feed_config()).entries[0]["summary"]
    assert truncated == summary[:DEFAULT_MAX_TEXT_LENGTH] + TRUNCATION_SUFFIX


def test_max_text_length_can_be_raised() -> None:
    """Test that a user can ask for more text than the default."""
    summary = "abcdefghij" * 300
    parsed = parse_feed(html_feed(summary), html_feed_config(max_text_length=1000))
    assert parsed.entries[0]["summary"] == summary[:1000] + TRUNCATION_SUFFIX


def test_max_text_length_zero_keeps_the_full_text() -> None:
    """Test that the truncation can be switched off entirely."""
    summary = "abcdefghij" * 300
    parsed = parse_feed(
        html_feed(summary),
        html_feed_config(max_text_length=NO_TEXT_LIMIT),
    )
    assert parsed.entries[0]["summary"] == summary


def test_oversized_attributes_are_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that a user learns why the recorder drops their attributes."""
    caplog.set_level(logging.WARNING)
    parse_feed(
        ZEIT_VERBRECHEN.read_bytes(),
        zeit_verbrechen_config(show_topn=100, max_text_length=NO_TEXT_LIMIT),
    )
    assert any(
        "zeit_verbrechen" in r.message and str(MAX_STATE_ATTRS_BYTES) in r.message
        for r in caplog.records
        if r.levelno == logging.WARNING
    ), "no warning about the recorder limit was logged"


def test_default_sized_feed_is_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that a feed within the limit does not warn."""
    caplog.set_level(logging.WARNING)
    parse_feed(ZEIT_VERBRECHEN.read_bytes(), zeit_verbrechen_config())
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_truncation_closes_the_inner_of_two_identical_tags() -> None:
    """Test that a nested element of the same name is closed once each.

    A summary that opens a second `<p>` inside the first is ordinary in RSS.
    Closing the inner one must not be taken as closing the outer one too, or
    the cut fragment is left with an unbalanced paragraph and no closing tag
    is appended for it.
    """
    summary = (
        "<p>" + "word " * 20 + "<p>inner</p>" + "tail words that go on " * 20 + "</p>"
    )
    assert summary.index("</p>") < DEFAULT_MAX_TEXT_LENGTH
    truncated = parse_feed(html_feed(summary), html_feed_config()).entries[0]["summary"]

    assert truncated.startswith("<p>")
    assert truncated.endswith(TRUNCATION_SUFFIX + "</p>")
    # the outer paragraph is still open at the cut and is closed again
    assert truncated.count("<p>") == truncated.count("</p>")


def test_truncation_does_not_cut_an_entity_before_a_later_tag() -> None:
    """Test that an entity at the cut survives a tag sitting behind it.

    The feed escapes the ampersand, so what reaches the truncation is the
    literal text `&nbsp;` - a character entity the reader is meant to see.
    It straddles the limit, and a `<br/>` sits further along; scanning the
    tags before the entities lets that tag end the scan first and the entity
    is cut into `&nbsp`.
    """
    keep = DEFAULT_MAX_TEXT_LENGTH - 5
    summary = "w" * keep + "&amp;nbsp;" + " rest" * 30 + "<br/>"
    truncated = parse_feed(html_feed(summary), html_feed_config()).entries[0]["summary"]

    assert not truncated.endswith("&nbsp" + TRUNCATION_SUFFIX)
    assert truncated == "w" * keep + TRUNCATION_SUFFIX


def test_a_tag_too_long_to_keep_does_not_take_the_text_with_it() -> None:
    """Test that an inline base64 image does not empty out the summary."""
    inline_image = '<img src="data:image/png;base64,' + "A" * 2000 + '"/>'
    text = "The words a reader actually came for, long enough to be cut. " * 10
    summary = inline_image + text
    assert len(inline_image) > DEFAULT_MAX_TEXT_LENGTH

    truncated = parse_feed(html_feed(summary), html_feed_config()).entries[0]["summary"]

    assert truncated != TRUNCATION_SUFFIX
    assert truncated.startswith("The words a reader actually came for")
    assert "base64" not in truncated
    assert len(truncated) <= DEFAULT_MAX_TEXT_LENGTH + len(TRUNCATION_SUFFIX)


def test_the_oversize_warning_is_not_repeated_on_every_poll(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that a polled feed logs the recorder warning once, not hourly."""
    caplog.set_level(logging.WARNING)
    config = zeit_verbrechen_config(show_topn=100, max_text_length=NO_TEXT_LIMIT)
    for _ in range(3):
        parse_feed(ZEIT_VERBRECHEN.read_bytes(), config)

    warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and str(MAX_STATE_ATTRS_BYTES) in r.message
    ]
    assert len(warnings) == 1, "the same warning was logged on every poll"


# One warning for each of the two configurations tried below.
EXPECTED_WARNINGS_PER_SETTING = 2


def test_the_oversize_warning_returns_when_the_settings_change(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that a user who changed the numbers is told they still do not fit."""
    caplog.set_level(logging.WARNING)
    parse_feed(
        ZEIT_VERBRECHEN.read_bytes(),
        zeit_verbrechen_config(show_topn=100, max_text_length=NO_TEXT_LIMIT),
    )
    parse_feed(
        ZEIT_VERBRECHEN.read_bytes(),
        zeit_verbrechen_config(show_topn=90, max_text_length=NO_TEXT_LIMIT),
    )

    warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and str(MAX_STATE_ATTRS_BYTES) in r.message
    ]
    assert len(warnings) == EXPECTED_WARNINGS_PER_SETTING


def test_parse_feed_with_topn(feed: FeedSource) -> None:
    """Test that only the topn entries are kept."""
    show_topn = 1
    parsed = parse_feed(
        feed.path.read_bytes(),
        FeedParserConfig(
            feed_url=feed.path.absolute().as_uri(),
            name=feed.name,
            date_format=DATE_FORMAT,
            local_time=False,
            show_topn=show_topn,
            remove_summary_image=False,
            inclusions=["image", "title", "link", "published"],
            exclusions=[],
        ),
    )
    assert parsed.entries

    # assert that the sensor value is equal to the number of
    # entries and that only top N entries are stored
    assert parsed.native_value == show_topn == len(parsed.entries)


@pytest.mark.parametrize(
    "local_time",
    [True, False],
    ids=["local_time", "default_time"],
)
def test_parse_feed_entries_time(
    feed: FeedSource,
    local_time: bool,
) -> None:
    """Test that the published date is converted to the configured timezone."""
    parsed = parse_local_feed(feed, local_time=local_time)
    assert parsed.entries

    # load the feed with feedparser
    parsed_source: feedparser.FeedParserDict = feedparser.parse(
        feed.path.absolute().as_uri(),
    )

    # get the first entry
    entry = parsed_source.entries[0]

    # get the time of the first entry
    first_entry_struct_time: time.struct_time = entry.published_parsed
    first_entry_time: datetime = datetime(
        *first_entry_struct_time[:6],
        tzinfo=UTC,
    )

    # get the time of the first parsed entry
    first_parsed_entry_time: datetime = datetime.strptime(  # noqa: DTZ007
        parsed.entries[0]["published"],
        feed.sensor_config.date_format,
    )

    if not first_parsed_entry_time.tzinfo:
        first_parsed_entry_time = first_parsed_entry_time.replace(tzinfo=UTC)

    # assert that the time of the first parsed entry is equal to
    # the time of the first entry in the feed
    assert first_entry_time == first_parsed_entry_time


def test_check_duplicates(feed: FeedSource) -> None:
    """Test that parsing twice yields the same number of entries."""
    first = parse_local_feed(feed)
    assert first.entries
    second = parse_local_feed(feed)
    assert len(first.entries) == len(second.entries)


def test_remove_summary_image(
    feed_with_image_in_summary: FeedSource,
) -> None:
    """Test that the image is removed from the summary."""
    feed = feed_with_image_in_summary
    parsed = parse_local_feed(feed, remove_summary_image=False)
    assert parsed.entries

    # assert that the image is not removed from the summary
    assert any(re.search(IMAGE_REGEX, e["summary"]) is not None for e in parsed.entries)

    parsed = parse_local_feed(feed, remove_summary_image=True)
    assert parsed.entries

    with nullcontext() if feed.all_entries_have_summary else suppress(KeyError):
        assert all("img" not in e["summary"] for e in parsed.entries)


def test_image_not_in_entries(feed: FeedSource) -> None:
    """Test that excluded images do not appear in any feed entry."""
    # keep only the title in the inclusions, but images are included by default
    # so we must explicitly exclude them if we don't want them
    parsed = parse_local_feed(feed, exclusions=["image"])
    assert parsed.entries
    # assert that the image is not included in the feed entries
    assert all("image" not in e for e in parsed.entries)


def test_media_thumbnail_support() -> None:
    """Test that media:thumbnail is correctly parsed."""
    feed_path = Path(__file__).parent / "data/zeit_verbrechen.xml"
    parsed = parse_feed(
        feed_path.read_bytes(),
        FeedParserConfig(
            feed_url=feed_path.absolute().as_uri(),
            name="bbc_europe",
            date_format=DATE_FORMAT,
            local_time=False,
            show_topn=9999,
            remove_summary_image=False,
            inclusions=["image", "title", "link", "published"],
            exclusions=[],
        ),
    )
    assert parsed.entries

    # Check if all entries have an image that is not the default one.
    assert all("image" in e for e in parsed.entries)

    # Check the first image url
    assert parsed.entries[0]["image"].startswith("https://")


def test_parse_feed_without_data() -> None:
    """Test that content which is not a feed yields no state."""
    parsed = parse_feed(
        b"not a feed at all",
        FeedParserConfig(
            feed_url="http://example.com/feed",
            name="empty",
            date_format=DATE_FORMAT,
            show_topn=10,
        ),
    )
    assert parsed.native_value is None
    assert parsed.entries == []


def test_parse_feed_without_entries() -> None:
    """Test that a valid feed with no items reports zero entries."""
    parsed = parse_feed(
        b'<?xml version="1.0"?><rss version="2.0"><channel>'
        b"<title>empty</title></channel></rss>",
        FeedParserConfig(
            feed_url="http://example.com/feed",
            name="empty",
            date_format=DATE_FORMAT,
            show_topn=10,
        ),
    )
    assert parsed.native_value == 0
    assert parsed.entries == []
    assert parsed.channel["title"] == "empty"


def test_relative_urls_are_resolved(feed: FeedSource) -> None:
    """Test that no entry keeps a relative image or link URL."""
    config = local_feed_config(feed)
    parsed = parse_feed(feed.path.read_bytes(), config)
    for entry in parsed.entries:
        for key in ("image", "link"):
            if value := entry.get(key):
                assert "://" in value, f"{key} was not resolved: {value}"


@pytest.mark.parametrize(
    ("value", "expected_minutes"),
    [
        (5, 5),
        ("15", 15),
        (60.0, 60),  # the UI number selector returns floats
        (0, MIN_SCAN_INTERVAL_MINUTES),  # too small, clamped
        (-10, MIN_SCAN_INTERVAL_MINUTES),
        (999999, MAX_SCAN_INTERVAL_MINUTES),  # too large, clamped
        (None, DEFAULT_SCAN_INTERVAL_MINUTES),  # unparsable, falls back
        ("nonsense", DEFAULT_SCAN_INTERVAL_MINUTES),
    ],
)
def test_scan_interval_from_minutes(
    value: str | int | float | None,
    expected_minutes: int,
) -> None:
    """Test conversion of the UI scan interval into a timedelta."""
    assert scan_interval_from_minutes(value) == timedelta(minutes=expected_minutes)
