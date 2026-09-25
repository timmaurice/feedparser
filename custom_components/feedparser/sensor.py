"""Feedparser sensor."""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.const import CONF_NAME, CONF_SCAN_INTERVAL
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DATE_FORMAT,
    CONF_EXCLUSIONS,
    CONF_FEED_URL,
    CONF_INCLUSIONS,
    CONF_LOCAL_TIME,
    CONF_MAX_TEXT_LENGTH,
    CONF_REMOVE_SUMMARY_IMG,
    CONF_SHOW_TOPN,
    DEFAULT_DATE_FORMAT,
    DEFAULT_MAX_TEXT_LENGTH,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    UNLIMITED_TOPN,
)
from .coordinator import FeedparserCoordinator
from .parser import FeedParserConfig, state_attributes

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceInfo
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

    from .coordinator import FeedparserConfigEntry

__version__ = "1.2.0"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_FEED_URL): cv.string,
        vol.Required(CONF_DATE_FORMAT, default=DEFAULT_DATE_FORMAT): cv.string,
        vol.Optional(CONF_LOCAL_TIME, default=False): cv.boolean,
        # A YAML sensor that never set show_topn keeps every entry, the way it
        # always did. The sensor's state is the number of entries, so capping it
        # here would rewrite the meaning of an existing recorder history and of
        # every template comparing that state.
        vol.Optional(CONF_SHOW_TOPN, default=UNLIMITED_TOPN): cv.positive_int,
        vol.Optional(
            CONF_MAX_TEXT_LENGTH,
            default=DEFAULT_MAX_TEXT_LENGTH,
        ): cv.positive_int,
        vol.Optional(CONF_REMOVE_SUMMARY_IMG, default=False): cv.boolean,
        vol.Optional(CONF_INCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_EXCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): cv.time_period,
    },
)

_LOGGER: logging.Logger = logging.getLogger(__name__)

# The coordinator does the fetching, and the entity only reads what it holds, so
# there is no per-entity update to serialise.
PARALLEL_UPDATES = 0

# Only a URL the browser can open belongs on the device page.
WEB_SCHEMES = frozenset({"http", "https"})


def yaml_unique_id(config: FeedParserConfig) -> str:
    """Return a stable unique_id for a YAML configured feed.

    Without one the entity is not in the entity registry at all, so it cannot
    be renamed, hidden or put in an area. The feed URL alone is not enough: two
    YAML sensors may watch the same feed under different names, and a shared
    unique_id would make Home Assistant drop the second entity. The name is
    part of the hash for that reason, and the id is derived rather than stored
    so it comes out the same on every restart.

    That makes the identity of a YAML sensor depend on two values a user may
    edit. Changing either mints a new one: the sensor comes up as a new entity
    and the registry keeps the old row, unavailable, holding the old entity id.
    Dropping the name from the hash would trade that for a hard failure - Home
    Assistant refuses the second entity of a colliding pair outright - so the
    trade is deliberate and the README says so. There is nothing to migrate
    here: the old name is not knowable from the new configuration, and YAML
    sensors had no unique_id at all before, where a rename changed the entity
    id just the same. A feed whose name is expected to change belongs in a UI
    entry, which is identified by its config entry.
    """
    fingerprint = f"{config.feed_url}\n{config.name}".encode()
    return f"yaml_{hashlib.sha256(fingerprint).hexdigest()[:16]}"


def device_info(config: FeedParserConfig, entry_id: str) -> DeviceInfo:
    """Return the device a UI configured feed's entity is grouped under."""
    # Built as a plain dict on purpose: DeviceInfo is a TypedDict, and the
    # module it lives in has moved between Home Assistant versions.
    info: DeviceInfo = {
        "identifiers": {(DOMAIN, entry_id)},
        "name": config.name,
        "manufacturer": "RSS",
        "model": "Feed",
    }
    if urlparse(config.feed_url).scheme in WEB_SCHEMES:
        info["configuration_url"] = config.feed_url
    return info


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,  # noqa: ARG001
) -> None:
    """Set up the Feedparser sensor from YAML.

    A YAML sensor has no config entry, so there is no `runtime_data` to put
    its coordinator on - and nothing needs to find it there: no unload, reload
    or diagnostics goes through a platform set up this way. The entity is the
    coordinator's only owner and listener, which is also what stops its
    polling when the entity is removed. Nothing is kept in `hass.data` for it.
    """
    parser_config = FeedParserConfig(
        feed_url=config[CONF_FEED_URL],
        name=config[CONF_NAME],
        date_format=config[CONF_DATE_FORMAT],
        show_topn=config[CONF_SHOW_TOPN],
        remove_summary_image=config[CONF_REMOVE_SUMMARY_IMG],
        max_text_length=config[CONF_MAX_TEXT_LENGTH],
        inclusions=config[CONF_INCLUSIONS],
        exclusions=config[CONF_EXCLUSIONS],
        local_time=config[CONF_LOCAL_TIME],
    )
    coordinator = FeedparserCoordinator(
        hass,
        parser_config,
        update_interval=config[CONF_SCAN_INTERVAL],
    )
    await coordinator.async_refresh()

    async_add_entities([FeedParserSensor(coordinator)])


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: FeedparserConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Feedparser sensor from a config entry."""
    async_add_entities(
        [FeedParserSensor(entry.runtime_data, entry_id=entry.entry_id)],
    )


class FeedParserSensor(CoordinatorEntity[FeedparserCoordinator], SensorEntity):
    """Representation of a Feedparser sensor."""

    _attr_has_entity_name = True
    # No force_update: Home Assistant already writes a new state whenever the
    # attributes change, so forcing one only makes every poll of an unchanged
    # feed a recorder write.

    # The icon comes from icons.json through this key, so it is not written into
    # every state. The key names no entity text: both kinds of sensor set
    # `_attr_name` below, and an explicit name wins over a translated one, so
    # `strings.json` has nothing to carry for it.
    _attr_translation_key = "feed"
    _attr_attribution = "Data retrieved using RSS feedparser"

    def __init__(
        self: FeedParserSensor,
        coordinator: FeedparserCoordinator,
        entry_id: str | None = None,
    ) -> None:
        """Initialize the Feedparser sensor."""
        super().__init__(coordinator)
        if entry_id:
            self._attr_unique_id = f"{entry_id}"
            self._attr_device_info = device_info(coordinator.config, entry_id)
            # The entity is the only thing on its device, so it takes the
            # device's name rather than appending its own to it - which is the
            # name it has always had.
            self._attr_name = None
        else:
            self._attr_unique_id = yaml_unique_id(coordinator.config)
            self._attr_name = coordinator.config.name
        _LOGGER.debug("Feed %s: FeedParserSensor initialized - %s", self.name, self)

    def __repr__(self: FeedParserSensor) -> str:
        """Return the representation."""
        config = self.coordinator.config
        return (
            f'FeedParserSensor(name="{config.name}", feed="{config.feed_url}", '
            f"show_topn={config.show_topn}, "
            f"remove_summary_image={config.remove_summary_image}, "
            f"inclusions={config.inclusions}, "
            f"exclusions={config.exclusions}, "
            f"scan_interval={self.coordinator.update_interval}, "
            f'local_time={config.local_time}, date_format="{config.date_format}")'
        )

    @property
    def native_value(self: FeedParserSensor) -> int | None:
        """Return the number of entries in the feed."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.native_value

    @property
    def channel(self: FeedParserSensor) -> dict[str, Any]:
        """Return channel info."""
        if self.coordinator.data is None:
            return {}
        return self.coordinator.data.channel

    @property
    def feed_entries(self: FeedParserSensor) -> list[dict[str, Any]]:
        """Return feed entries."""
        if self.coordinator.data is None:
            return []
        return self.coordinator.data.entries

    @property
    def local_time(self: FeedParserSensor) -> bool:
        """Return local_time."""
        return self.coordinator.config.local_time

    @property
    def feed_url(self: FeedParserSensor) -> str:
        """Return the URL the feed is polled from."""
        return self.coordinator.config.feed_url

    @property
    def extra_state_attributes(self: FeedParserSensor) -> dict[str, Any]:
        """Return entity specific state attributes."""
        return state_attributes(self.feed_url, self.channel, self.feed_entries)
