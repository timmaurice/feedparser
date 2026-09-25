"""Tests the feedparser sensor entity."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from conftest import parse_local_feed

from custom_components.feedparser.const import (
    CONF_MAX_TEXT_LENGTH,
    CONF_SHOW_TOPN,
    DEFAULT_MAX_TEXT_LENGTH,
    DEFAULT_TOPN,
    DOMAIN,
    MAX_STATE_ATTRS_BYTES,
    UNLIMITED_TOPN,
)
from custom_components.feedparser.sensor import (
    PARALLEL_UPDATES,
    PLATFORM_SCHEMA,
    FeedParserSensor,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from feedsource import FeedSource

    from custom_components.feedparser.parser import ParsedFeed


# What a YAML sensor without show_topn must keep doing: every entry.
EXPECTED_YAML_TOPN = 9999
EXPECTED_CONFIGURED_TOPN = 3


SENSOR_FEED_URL = "https://example.com/feed.xml"
SENSOR_ENTRY_ID = "01JICONTRANSLATIONS00000"

INTEGRATION_DIR = Path(__file__).parent.parent / "custom_components" / DOMAIN


def build_sensor(
    parsed: ParsedFeed,
    name: str,
    entry_id: str | None = None,
) -> FeedParserSensor:
    """Return a sensor backed by an already parsed feed.

    Without `entry_id` it is a YAML sensor, with one a UI entry's.
    """
    coordinator = MagicMock()
    coordinator.config.name = name
    coordinator.config.feed_url = SENSOR_FEED_URL
    coordinator.data = parsed
    return FeedParserSensor(coordinator, entry_id=entry_id)


def on_a_platform(sensor: FeedParserSensor) -> FeedParserSensor:
    """Put the sensor on a platform whose translations would name its key.

    An entity with a translation key cannot compute its state before it is on
    a platform. `strings.json` carries no name for the key, but one added later
    must not rename anything either, so the platform offers one: it is what
    Home Assistant would use for an entity that has no name of its own.
    """
    platform_data = MagicMock()
    platform_data.platform_name = DOMAIN
    platform_data.domain = "sensor"
    platform_data.platform_translations = {
        f"component.{DOMAIN}.entity.sensor.{sensor.translation_key}.name": "Feed",
    }
    sensor.platform_data = platform_data
    return sensor


def written_attributes(sensor: FeedParserSensor) -> Mapping[str, Any]:
    """Return the attributes Home Assistant would write into the state.

    `extra_state_attributes` is only part of them: the icon, the friendly
    name and the attribution are added by the entity base class.
    """
    return sensor._async_calculate_state().attributes  # noqa: SLF001


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


def test_the_platform_does_not_limit_parallel_updates() -> None:
    """Test that the sensor platform sets no update limit.

    The entity reads what the coordinator holds and fetches nothing itself, so
    there is no per-entity update for Home Assistant to serialise.
    """
    assert PARALLEL_UPDATES == 0


def test_the_state_carries_no_icon(feed: FeedSource) -> None:
    """Test that the icon is left to icons.json.

    With `_attr_icon` every state, and so every recorder row, carried
    `icon: mdi:rss`. The frontend now resolves it from the translation key.
    An icon a user picks for the entity is a registry value and is still
    written, which this sensor without a registry entry cannot show.
    """
    sensor = on_a_platform(
        build_sensor(parse_local_feed(feed, show_topn=DEFAULT_TOPN), feed.name),
    )
    assert sensor.icon is None
    assert "icon" not in written_attributes(sensor)


def test_icons_json_has_an_icon_for_the_translation_key() -> None:
    """Test that the key the sensor sets is the one icons.json answers for.

    A key that icons.json does not know leaves the sensor with the generic
    sensor icon, and nothing would fail at runtime to say so.
    """
    sensor = build_sensor(MagicMock(), "Some Feed")
    icons = json.loads((INTEGRATION_DIR / "icons.json").read_text())
    assert sensor.translation_key == "feed"
    assert icons["entity"]["sensor"][sensor.translation_key] == {
        "default": "mdi:rss",
    }


def test_a_ui_sensor_keeps_the_device_name(feed: FeedSource) -> None:
    """Test that a UI entry is still named by its device, the user's feed name.

    A translation key would name an entity that has no name of its own. The
    entry sets `_attr_name = None`, which Home Assistant takes over any
    translated name, so the entity keeps the device's name - and its entity id.
    """
    parsed = parse_local_feed(feed, show_topn=DEFAULT_TOPN)
    sensor = build_sensor(parsed, feed.name, entry_id=SENSOR_ENTRY_ID)
    assert sensor.name is None
    translated = on_a_platform(
        build_sensor(parsed, feed.name, entry_id=SENSOR_ENTRY_ID),
    )
    assert translated.name is None
    assert sensor.device_info is not None
    assert sensor.device_info["name"] == feed.name


def test_a_yaml_sensor_keeps_its_configured_name(feed: FeedSource) -> None:
    """Test that a YAML sensor is still named what its configuration says.

    Its name is part of its entity id and of its unique_id, so a translated
    name taking over would rename the sensor and mint a new entity.
    """
    parsed = parse_local_feed(feed, show_topn=DEFAULT_TOPN)
    sensor = on_a_platform(build_sensor(parsed, feed.name))
    assert sensor.name == feed.name
    assert written_attributes(sensor)["friendly_name"] == feed.name
