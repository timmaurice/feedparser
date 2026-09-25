"""Tests where a config entry's coordinator lives between setup and unload.

The coordinator is kept on `entry.runtime_data`, not in `hass.data`. These
tests run the integration's own setup, unload and sensor platform against a
real `ConfigEntry` - the attribute's lifecycle is the core's, so a fake entry
would only pin what the fake does - and a hass that holds nothing else.
"""

from __future__ import annotations

import asyncio
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryNotReady

import custom_components.feedparser as integration
from custom_components.feedparser import sensor
from custom_components.feedparser.const import DOMAIN
from custom_components.feedparser.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.feedparser.parser import FeedParserConfig

if TYPE_CHECKING:
    from datetime import timedelta

    from homeassistant.helpers.entity import Entity

ENTRY_ID = "01JRUNTIMEDATA0000000000"
FEED_URL = "https://example.com/feed.xml"


class FakeCoordinator:
    """Stands in for the coordinator: records the refreshes it is asked for."""

    def __init__(
        self: FakeCoordinator,
        hass: object | None = None,  # noqa: ARG002
        config: FeedParserConfig | None = None,
        update_interval: timedelta | None = None,
        *,
        fails: bool = False,
    ) -> None:
        """Initialize."""
        self.config = config or FeedParserConfig(
            feed_url=FEED_URL,
            name="Some Feed",
            date_format="%a, %d %b %Y %H:%M:%S",
            show_topn=5,
        )
        self.update_interval = update_interval
        self.data = None
        self.last_update_success = True
        self.fails = fails
        self.refreshes = 0

    async def async_config_entry_first_refresh(self: FakeCoordinator) -> None:
        """Refresh the way setup does, raising what the core would."""
        self.refreshes += 1
        if self.fails:
            msg = "feed unreachable"
            raise ConfigEntryNotReady(msg)

    async def async_refresh(self: FakeCoordinator) -> None:
        """Refresh the way the YAML platform does."""
        self.refreshes += 1


class FakeConfigEntries:
    """Records what setup and unload ask of `hass.config_entries`."""

    def __init__(self: FakeConfigEntries, *, unload_ok: bool = True) -> None:
        """Initialize."""
        self.forwarded: list[tuple[ConfigEntry, list[str]]] = []
        self.unloaded: list[ConfigEntry] = []
        self.reloaded: list[str] = []
        self.unload_ok = unload_ok

    async def async_forward_entry_setups(
        self: FakeConfigEntries,
        entry: ConfigEntry,
        platforms: list[str],
    ) -> None:
        """Record the platforms an entry is forwarded to."""
        self.forwarded.append((entry, list(platforms)))

    async def async_unload_platforms(
        self: FakeConfigEntries,
        entry: ConfigEntry,
        platforms: list[str],  # noqa: ARG002
    ) -> bool:
        """Record an unload and answer what the platforms would."""
        self.unloaded.append(entry)
        return self.unload_ok

    async def async_reload(self: FakeConfigEntries, entry_id: str) -> bool:
        """Record a reload."""
        self.reloaded.append(entry_id)
        return True


class FakeHass:
    """A hass whose `data` starts empty, so anything written to it shows."""

    def __init__(self: FakeHass, *, unload_ok: bool = True) -> None:
        """Initialize."""
        self.data: dict[str, Any] = {}
        self.config_entries = FakeConfigEntries(unload_ok=unload_ok)


def a_config_entry() -> ConfigEntry:
    """Return a real, not yet set up config entry of this integration."""
    return ConfigEntry(
        data={"name": "Some Feed", "feed_url": FEED_URL},
        discovery_keys=MappingProxyType({}),
        domain=DOMAIN,
        entry_id=ENTRY_ID,
        minor_version=1,
        options={},
        source="user",
        subentries_data=None,
        title="Some Feed",
        unique_id=FEED_URL,
        version=integration.CONFIG_ENTRY_VERSION,
    )


def set_up(
    monkeypatch: pytest.MonkeyPatch,
    coordinator: FakeCoordinator,
    entry: ConfigEntry,
    hass: FakeHass,
) -> bool:
    """Run the integration's setup with `coordinator` as what it builds."""
    monkeypatch.setattr(integration, "build_coordinator", lambda *_: coordinator)
    return asyncio.run(
        integration.async_setup_entry(hass, entry),  # type: ignore[arg-type]
    )


def test_setup_puts_the_coordinator_on_the_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that the coordinator travels with its entry, not through hass.data.

    The sensor platform and diagnostics both find it on `entry.runtime_data`,
    so a coordinator left in `hass.data` as well would be a second copy nothing
    keeps in step with the entry.
    """
    coordinator = FakeCoordinator()
    entry = a_config_entry()
    hass = FakeHass()
    assert set_up(monkeypatch, coordinator, entry, hass) is True
    assert entry.runtime_data is coordinator
    assert coordinator.refreshes == 1
    assert hass.data == {}
    assert hass.config_entries.forwarded == [(entry, integration.PLATFORMS)]


def test_setup_still_reloads_the_entry_on_an_option_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that the update listener is registered and reloads the entry.

    The options - the update interval above all - are read once, when the
    coordinator is built, so an option change only takes effect through the
    reload this listener triggers.
    """
    entry = a_config_entry()
    hass = FakeHass()
    set_up(monkeypatch, FakeCoordinator(), entry, hass)
    assert entry.update_listeners == [integration.update_listener]
    asyncio.run(
        entry.update_listeners[0](hass, entry),  # type: ignore[arg-type]
    )
    assert hass.config_entries.reloaded == [ENTRY_ID]


def test_a_feed_that_is_not_ready_leaves_no_runtime_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that an entry whose first refresh failed carries no coordinator.

    Diagnostics tells an entry that never set up from one that did by the
    attribute being absent, so setup must not assign it before the first
    refresh went through - and must not forward to the sensor platform either.
    """
    entry = a_config_entry()
    hass = FakeHass()
    with pytest.raises(ConfigEntryNotReady):
        set_up(monkeypatch, FakeCoordinator(fails=True), entry, hass)
    assert not hasattr(entry, "runtime_data")
    assert hass.config_entries.forwarded == []
    assert hass.data == {}


@pytest.mark.parametrize("unload_ok", [True, False])
def test_unload_answers_what_the_platforms_answered(
    monkeypatch: pytest.MonkeyPatch,
    unload_ok: bool,
) -> None:
    """Test that unload leaves the coordinator to the core.

    Home Assistant deletes `runtime_data` itself after an unload that
    succeeded and keeps it after one that failed. The integration only has to
    pass the platforms' answer on, and must not need `hass.data` to do it.
    """
    entry = a_config_entry()
    hass = FakeHass(unload_ok=unload_ok)
    coordinator = FakeCoordinator()
    set_up(monkeypatch, coordinator, entry, hass)
    unloaded = asyncio.run(
        integration.async_unload_entry(hass, entry),  # type: ignore[arg-type]
    )
    assert unloaded is unload_ok
    assert hass.config_entries.unloaded == [entry]
    assert entry.runtime_data is coordinator
    assert hass.data == {}


def test_the_sensor_platform_takes_the_coordinator_from_the_entry() -> None:
    """Test that the entity is built on the coordinator setup stored."""
    coordinator = FakeCoordinator()
    entry = a_config_entry()
    entry.runtime_data = coordinator
    added: list[Entity] = []
    asyncio.run(
        sensor.async_setup_entry(
            FakeHass(),  # type: ignore[arg-type]
            entry,
            lambda entities, *_: added.extend(entities),
        ),
    )
    assert len(added) == 1
    entity = added[0]
    assert isinstance(entity, sensor.FeedParserSensor)
    assert entity.coordinator is coordinator
    assert entity.unique_id == ENTRY_ID


def test_a_yaml_sensor_needs_neither_an_entry_nor_hass_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that the legacy platform keeps working without a config entry.

    A YAML sensor has no entry to carry its coordinator, so the entity holds
    it directly. It must not fall back to parking it in `hass.data`, where
    nothing would ever remove it.
    """
    built: list[FakeCoordinator] = []

    def build(*args: Any, **kwargs: Any) -> FakeCoordinator:  # noqa: ANN401
        built.append(FakeCoordinator(*args, **kwargs))
        return built[-1]

    monkeypatch.setattr(sensor, "FeedparserCoordinator", build)
    config = sensor.PLATFORM_SCHEMA(
        {
            "platform": DOMAIN,
            "name": "Some Feed",
            "feed_url": FEED_URL,
            "date_format": "%a, %d %b %Y %H:%M:%S",
        },
    )
    hass = FakeHass()
    added: list[Entity] = []
    asyncio.run(
        sensor.async_setup_platform(
            hass,  # type: ignore[arg-type]
            config,
            lambda entities, *_: added.extend(entities),
        ),
    )
    assert len(built) == 1
    assert built[0].refreshes == 1
    assert len(added) == 1
    entity = added[0]
    assert isinstance(entity, sensor.FeedParserSensor)
    assert entity.coordinator is built[0]
    assert entity.unique_id == sensor.yaml_unique_id(built[0].config)
    assert hass.data == {}


def test_diagnostics_of_a_real_entry_that_never_set_up() -> None:
    """Test the guard against the core's entry, not against a double.

    A `ConfigEntry` that never set up has no `runtime_data` attribute at all,
    and reading it raises. The report has to come out anyway, because that is
    the entry somebody downloads diagnostics for.
    """
    entry = a_config_entry()
    with pytest.raises(AttributeError):
        _ = entry.runtime_data
    report = asyncio.run(
        async_get_config_entry_diagnostics(
            FakeHass(),  # type: ignore[arg-type]
            entry,
        ),
    )
    assert "setup" in report
    assert report["entry"]["data"]["feed_url"] == FEED_URL
