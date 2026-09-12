"""Tests the diagnostics platform and the entity identity of a sensor."""

from __future__ import annotations

import asyncio
from typing import Any

from constants import DATA_PATH

from custom_components.feedparser.const import DOMAIN, MAX_STATE_ATTRS_BYTES
from custom_components.feedparser.diagnostics import (
    async_get_config_entry_diagnostics,
    redact_url,
)
from custom_components.feedparser.parser import (
    FeedParserConfig,
    attributes_size,
    parse_feed,
)
from custom_components.feedparser.sensor import (
    FeedParserSensor,
    device_info,
    yaml_unique_id,
)

FEED = DATA_PATH / "ntv.xml"
ENTRY_ID = "01JABCDEF0123456789"
DATE_FORMAT = "%a, %d %b %Y %H:%M:%S"
# What the fixture is asked for, spelled out so the assertions read as counts.
SHOWN_ENTRIES = 3
ENTRY_VERSION = 4


def parser_config(**overrides: Any) -> FeedParserConfig:  # noqa: ANN401
    """Return a config pointing at a shipped fixture."""
    defaults: dict[str, Any] = {
        "feed_url": FEED.absolute().as_uri(),
        "name": "ntv",
        "date_format": DATE_FORMAT,
        "show_topn": SHOWN_ENTRIES,
    }
    return FeedParserConfig(**(defaults | overrides))


class FakeCoordinator:
    """The parts of the coordinator diagnostics and the entity read."""

    def __init__(self: FakeCoordinator, config: FeedParserConfig) -> None:
        """Initialize."""
        self.config = config
        self.data = parse_feed(FEED.read_bytes(), config)
        self.last_update_success = True
        self.update_interval = None


class FakeEntry:
    """The parts of a config entry diagnostics reads."""

    version = ENTRY_VERSION
    entry_id = ENTRY_ID

    def __init__(self: FakeEntry, data: dict[str, Any]) -> None:
        """Initialize."""
        self.data = data
        self.options: dict[str, Any] = {"show_topn": SHOWN_ENTRIES}


class FakeHass:
    """Just enough of hass to hold a coordinator."""

    def __init__(self: FakeHass, coordinator: FakeCoordinator) -> None:
        """Initialize."""
        self.data = {DOMAIN: {ENTRY_ID: coordinator}}


def diagnostics(url: str = "https://example.com/feed.xml") -> dict[str, Any]:
    """Run the diagnostics platform against a parsed fixture."""
    coordinator = FakeCoordinator(parser_config())
    hass = FakeHass(coordinator)
    entry = FakeEntry({"name": "ntv", "feed_url": url})
    return asyncio.run(
        async_get_config_entry_diagnostics(hass, entry),  # type: ignore[arg-type]
    )


def test_diagnostics_report_the_last_poll() -> None:
    """Test that the download says what the feed produced.

    Without it, a report about entries that are missing or a history without
    attributes has nothing in it to tell those two apart.
    """
    report = diagnostics()
    assert report["feed"]["entry_count"] == SHOWN_ENTRIES
    assert report["feed"]["state"] == SHOWN_ENTRIES
    assert "title" in report["feed"]["entry_keys"]
    assert report["feed"]["channel_keys"]
    assert report["coordinator"]["last_update_success"] is True
    assert report["entry"]["version"] == ENTRY_VERSION
    assert report["parser_config"]["show_topn"] == SHOWN_ENTRIES
    assert report["feed"]["recorder_limit_bytes"] == MAX_STATE_ATTRS_BYTES
    assert report["feed"]["state_attributes_bytes"] > 0
    assert report["feed"]["exceeds_recorder_limit"] in (True, False)


def test_diagnostics_keep_the_entries_out() -> None:
    """Test that the download reports the shape of the entries, not the text."""
    report = diagnostics()
    assert "entries" not in report["feed"]
    assert all(isinstance(key, str) for key in report["feed"]["entry_keys"])


def test_diagnostics_redact_a_secret_in_the_feed_url() -> None:
    """Test that a token in the URL does not travel into a GitHub issue."""
    report = diagnostics("https://user:pw@example.com/feed.xml?api_key=hunter2")
    reported = report["entry"]["data"]["feed_url"]
    assert "hunter2" not in reported
    assert "pw@" not in reported
    assert "example.com/feed.xml" in reported


def test_redact_url_keeps_a_plain_url_readable() -> None:
    """Test that a URL with nothing to hide is reported as it is."""
    assert redact_url("https://example.com/rss") == "https://example.com/rss"


def test_a_yaml_sensor_has_a_unique_id() -> None:
    """Test that a YAML feed can be renamed and put in an area.

    An entity without a unique_id is not in the entity registry at all, which
    is what left YAML feeds unmanageable in the UI.
    """
    sensor = FeedParserSensor(
        FakeCoordinator(parser_config()),  # type: ignore[arg-type]
    )
    assert sensor.unique_id
    assert sensor._attr_name == "ntv"  # noqa: SLF001
    assert sensor.device_info is None


def test_two_yaml_sensors_on_one_feed_do_not_collide() -> None:
    """Test that the name is part of the id.

    Two YAML sensors may watch the same feed under different names, and a
    shared unique_id would make Home Assistant drop the second entity.
    """
    first = yaml_unique_id(parser_config(name="one"))
    second = yaml_unique_id(parser_config(name="two"))
    assert first != second
    assert first == yaml_unique_id(parser_config(name="one"))


def test_a_ui_sensor_is_grouped_under_a_device() -> None:
    """Test that a config entry's entity gets a device to sit on."""
    sensor = FeedParserSensor(
        FakeCoordinator(parser_config()),  # type: ignore[arg-type]
        entry_id=ENTRY_ID,
    )
    assert sensor.unique_id == ENTRY_ID
    assert sensor.device_info is not None
    assert sensor.device_info["identifiers"] == {(DOMAIN, ENTRY_ID)}
    assert sensor.device_info["name"] == "ntv"
    # The device carries the name, so the entity must not append its own -
    # otherwise the friendly name of an existing sensor becomes "ntv ntv".
    assert sensor._attr_name is None  # noqa: SLF001


def test_a_file_feed_gets_no_configuration_url() -> None:
    """Test that only a URL a browser can open reaches the device page."""
    assert "configuration_url" not in device_info(parser_config(), ENTRY_ID)
    web = device_info(parser_config(feed_url="https://example.com/f.xml"), ENTRY_ID)
    assert web["configuration_url"] == "https://example.com/f.xml"


def test_diagnostics_survive_an_entry_that_never_set_up() -> None:
    """Test that a failed entry gets a report rather than a traceback.

    An entry whose setup failed has no coordinator in `hass.data`, and it is
    the entry somebody is most likely to download diagnostics for. Reading it
    unguarded made the download raise a KeyError on exactly that entry.
    """
    hass = FakeHass(FakeCoordinator(parser_config()))
    hass.data[DOMAIN] = {}
    entry = FakeEntry({"name": "ntv", "feed_url": "https://user:pw@example.com/f.xml"})
    report = asyncio.run(
        async_get_config_entry_diagnostics(hass, entry),  # type: ignore[arg-type]
    )
    assert report["entry"]["version"] == ENTRY_VERSION
    assert "pw@" not in report["entry"]["data"]["feed_url"]
    assert "setup" in report


def test_redact_url_hides_a_token_in_the_path() -> None:
    """Test that a private podcast feed does not leak its subscriber token.

    Patreon, Supporting Cast and the like put the token in the path rather than
    in the query string - `/feeds/<token>/rss` - which is exactly the URL a
    report ending up in a GitHub issue must not carry.
    """
    reported = redact_url("https://ex.com/feeds/8a3f1b2c9d4e5f60/rss")
    assert "8a3f1b2c9d4e5f60" not in reported
    assert reported.startswith("https://ex.com/feeds/")
    assert reported.endswith("/rss")
    uuid = redact_url("https://ex.com/p/550e8400-e29b-41d4-a716-446655440000/feed")
    assert "550e8400" not in uuid


def test_redact_url_keeps_a_readable_path_readable() -> None:
    """Test that the path still says which feed the report is about."""
    for url in (
        "https://ex.com/rss/matter_energy/engineering.xml",
        "https://www1.wdr.de/mediathek/audio/wdr-aktuell-news/wdr-aktuell-152.podcast",
    ):
        assert redact_url(url) == url


def test_a_renamed_yaml_feed_is_a_new_entity() -> None:
    """Test the documented price of putting the name in the YAML unique id.

    The name is hashed so that two sensors on one feed do not collide, which
    means editing `name` or `feed_url` mints a new identity rather than
    renaming the entity in place. That is what the README tells users, and this
    is what would notice if the id quietly started ignoring one of them.
    """
    original = yaml_unique_id(parser_config(name="one"))
    assert yaml_unique_id(parser_config(name="two")) != original
    assert yaml_unique_id(parser_config(feed_url="https://ex.com/f.xml")) != original
    assert yaml_unique_id(parser_config(name="one")) == original


def test_the_reported_size_is_the_size_of_what_is_written() -> None:
    """Test that diagnostics measures the attributes the sensor actually has.

    The dict was spelled out in three places - here, in the sensor, and in the
    recorder warning - so adding a key to one of them quietly turned the
    reported size into the size of something else. They share one builder now,
    and this is what holds them together.
    """
    coordinator = FakeCoordinator(parser_config())
    sensor = FeedParserSensor(coordinator)  # type: ignore[arg-type]
    written = attributes_size(sensor.extra_state_attributes)
    assert diagnostics()["feed"]["state_attributes_bytes"] == written


def test_diagnostics_still_redact_a_url_the_sensor_shows_in_full() -> None:
    """Test that exposing the URL on the entity did not reach the report.

    The entity's audience is whoever can open the config entry anyway; a
    diagnostics download is meant to be pasted into a GitHub issue, so a
    private feed's token has to stay out of it.
    """
    secret = "https://user:pw@example.com/feeds/Ab3xY9zQ1mN7pL2k/rss?token=abc"
    coordinator = FakeCoordinator(parser_config(feed_url=secret))
    sensor = FeedParserSensor(coordinator)  # type: ignore[arg-type]
    assert sensor.extra_state_attributes["feed_url"] == secret

    report = diagnostics(url=secret)
    assert "abc" not in report["entry"]["data"]["feed_url"]
    assert "Ab3xY9zQ1mN7pL2k" not in report["parser_config"]["feed_url"]
