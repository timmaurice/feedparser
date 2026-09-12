"""Tests the feedparser sensor entity."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from conftest import parse_local_feed

from custom_components.feedparser.const import (
    CONF_MAX_TEXT_LENGTH,
    CONF_SHOW_TOPN,
    DEFAULT_MAX_TEXT_LENGTH,
    DEFAULT_TOPN,
    MAX_STATE_ATTRS_BYTES,
    UNLIMITED_TOPN,
)
from custom_components.feedparser.sensor import PLATFORM_SCHEMA, FeedParserSensor

if TYPE_CHECKING:
    from feedsource import FeedSource

    from custom_components.feedparser.parser import ParsedFeed


# What a YAML sensor without show_topn must keep doing: every entry.
EXPECTED_YAML_TOPN = 9999
EXPECTED_CONFIGURED_TOPN = 3


SENSOR_FEED_URL = "https://example.com/feed.xml"


def build_sensor(parsed: ParsedFeed, name: str) -> FeedParserSensor:
    """Return a sensor backed by an already parsed feed."""
    coordinator = MagicMock()
    coordinator.config.name = name
    coordinator.config.feed_url = SENSOR_FEED_URL
    coordinator.data = parsed
    return FeedParserSensor(coordinator)


def test_sensor_does_not_force_update(feed: FeedSource) -> None:
    """Test that an unchanged feed does not force a state write.

    Home Assistant skips the state write when neither the state nor the
    attributes changed - but only for entities that do not ask for
    force_update. With it, every poll of an unchanged feed is a recorder write.
    """
    parsed = parse_local_feed(feed, show_topn=DEFAULT_TOPN)
    sensor = build_sensor(parsed, feed.name)
    assert sensor.force_update is False


def test_attributes_stay_below_recorder_limit(feed: FeedSource) -> None:
    """Test that the default attributes of a feed survive the recorder."""
    # no inclusions: the worst case, every key the feed offers is kept
    parsed = parse_local_feed(feed, show_topn=DEFAULT_TOPN, inclusions=[])
    sensor = build_sensor(parsed, feed.name)
    size = len(json.dumps(sensor.extra_state_attributes, default=str).encode())
    assert (
        size < MAX_STATE_ATTRS_BYTES
    ), f"{feed.name}: attributes are {size} bytes, the recorder would drop them"


def test_yaml_without_show_topn_keeps_every_entry() -> None:
    """Test that a YAML sensor is not silently capped by the new default.

    The sensor's state is the number of entries, so capping an existing YAML
    sensor would rewrite what its recorder history and every template built on
    that state mean. Those users have to opt in by setting show_topn.
    """
    validated = PLATFORM_SCHEMA(
        {
            "platform": "feedparser",
            "name": "Some Feed",
            "feed_url": "https://example.com/feed",
            "date_format": "%a, %d %b %Y %H:%M:%S",
        },
    )
    assert validated[CONF_SHOW_TOPN] == UNLIMITED_TOPN == EXPECTED_YAML_TOPN
    assert validated[CONF_SHOW_TOPN] != DEFAULT_TOPN
    # the text limit does apply, it does not change the state, only its size
    assert validated[CONF_MAX_TEXT_LENGTH] == DEFAULT_MAX_TEXT_LENGTH


def test_yaml_show_topn_is_still_honoured() -> None:
    """Test that a YAML sensor that sets show_topn gets what it asked for."""
    validated = PLATFORM_SCHEMA(
        {
            "platform": "feedparser",
            "name": "Some Feed",
            "feed_url": "https://example.com/feed",
            "date_format": "%a, %d %b %Y %H:%M:%S",
            "show_topn": EXPECTED_CONFIGURED_TOPN,
            "max_text_length": 0,
        },
    )
    assert validated[CONF_SHOW_TOPN] == EXPECTED_CONFIGURED_TOPN
    assert validated[CONF_MAX_TEXT_LENGTH] == 0


def test_the_sensor_shows_which_feed_it_polls(feed: FeedSource) -> None:
    """Test that the feed URL is readable without opening the configuration.

    It was write-once before: stored on the config entry, not shown by the
    options form, and never shown at all for a YAML sensor - so a feed that
    had been running for a year could not be told apart from another one.
    """
    parsed = parse_local_feed(feed, show_topn=DEFAULT_TOPN)
    sensor = build_sensor(parsed, feed.name)
    assert sensor.extra_state_attributes["feed_url"] == SENSOR_FEED_URL


def test_the_sensor_still_carries_channel_and_entries(feed: FeedSource) -> None:
    """Test that nothing built on the existing attributes lost them."""
    parsed = parse_local_feed(feed, show_topn=DEFAULT_TOPN)
    attributes = build_sensor(parsed, feed.name).extra_state_attributes
    assert attributes["entries"] == parsed.entries
    assert attributes["channel"] == parsed.channel


def test_a_feed_that_has_not_been_polled_yet_has_no_attributes(
    feed: FeedSource,
) -> None:
    """Test that the attributes survive a coordinator without data.

    The first poll can fail, and `extra_state_attributes` is read before it
    ever succeeds - the URL is the one thing that is known even then.
    """
    sensor = build_sensor(parse_local_feed(feed, show_topn=DEFAULT_TOPN), feed.name)
    sensor.coordinator.data = None
    attributes = sensor.extra_state_attributes
    assert attributes == {
        "feed_url": SENSOR_FEED_URL,
        "channel": {},
        "entries": [],
    }
