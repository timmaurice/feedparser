"""Feedparser sensor."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

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
    CONF_REMOVE_SUMMARY_IMG,
    CONF_SHOW_TOPN,
    DEFAULT_DATE_FORMAT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TOPN,
    DOMAIN,
)
from .coordinator import FeedparserCoordinator
from .parser import FeedParserConfig

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

__version__ = "1.0.5"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_FEED_URL): cv.string,
        vol.Required(CONF_DATE_FORMAT, default=DEFAULT_DATE_FORMAT): cv.string,
        vol.Optional(CONF_LOCAL_TIME, default=False): cv.boolean,
        vol.Optional(CONF_SHOW_TOPN, default=DEFAULT_TOPN): cv.positive_int,
        vol.Optional(CONF_REMOVE_SUMMARY_IMG, default=False): cv.boolean,
        vol.Optional(CONF_INCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_EXCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): cv.time_period,
    },
)

_LOGGER: logging.Logger = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,  # noqa: ARG001
) -> None:
    """Set up the Feedparser sensor from YAML."""
    parser_config = FeedParserConfig(
        feed_url=config[CONF_FEED_URL],
        name=config[CONF_NAME],
        date_format=config[CONF_DATE_FORMAT],
        show_topn=config[CONF_SHOW_TOPN],
        remove_summary_image=config[CONF_REMOVE_SUMMARY_IMG],
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
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Feedparser sensor from a config entry."""
    coordinator: FeedparserCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([FeedParserSensor(coordinator, entry_id=entry.entry_id)])


class FeedParserSensor(CoordinatorEntity[FeedparserCoordinator], SensorEntity):
    """Representation of a Feedparser sensor."""

    _attr_has_entity_name = True
    _attr_force_update = True
    _attr_icon = "mdi:rss"
    _attr_attribution = "Data retrieved using RSS feedparser"

    def __init__(
        self: FeedParserSensor,
        coordinator: FeedparserCoordinator,
        entry_id: str | None = None,
    ) -> None:
        """Initialize the Feedparser sensor."""
        super().__init__(coordinator)
        self._attr_name = coordinator.config.name
        if entry_id:
            self._attr_unique_id = f"{entry_id}"
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
    def extra_state_attributes(self: FeedParserSensor) -> dict[str, Any]:
        """Return entity specific state attributes."""
        return {"channel": self.channel, "entries": self.feed_entries}
