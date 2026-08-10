"""Tests the feedparser parsing layer."""

from __future__ import annotations

import re
from contextlib import nullcontext, suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import feedparser
import pytest
from conftest import local_feed_config, parse_local_feed
from constants import DATE_FORMAT
from feedsource import FeedSource

from custom_components.feedparser.const import (
    DEFAULT_SCAN_INTERVAL_MINUTES,
    IMAGE_REGEX,
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
    scan_interval_from_minutes,
)
from custom_components.feedparser.parser import (
    FeedParserConfig,
    ParsedFeed,
    parse_feed,
)

if TYPE_CHECKING:
    import time


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
        tzinfo=timezone.utc,
    )

    # get the time of the first parsed entry
    first_parsed_entry_time: datetime = datetime.strptime(  # noqa: DTZ007
        parsed.entries[0]["published"],
        feed.sensor_config.date_format,
    )

    if not first_parsed_entry_time.tzinfo:
        first_parsed_entry_time = first_parsed_entry_time.replace(tzinfo=timezone.utc)

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
