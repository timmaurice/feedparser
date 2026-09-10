"""A component which allows you to parse an RSS feed into a sensor."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.const import Platform

from .const import CONF_SHOW_TOPN, DEFAULT_TOPN, DOMAIN, UNLIMITED_TOPN
from .coordinator import build_coordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

CONFIG_ENTRY_VERSION = 2


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Feedparser from a config entry."""
    coordinator = build_coordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate an old config entry."""
    if entry.version >= CONFIG_ENTRY_VERSION:
        return True

    # Version 1 entries were written by a config flow whose form default was
    # UNLIMITED_TOPN, and voluptuous materialised that default into the stored
    # data even when the user never touched the field. Such an entry keeps
    # every entry of its feed and pushes the state attributes past what the
    # recorder stores, so move it onto the new default. Any other number is a
    # value somebody chose and is left alone.
    data = dict(entry.data)
    options = dict(entry.options)
    for values in (data, options):
        if values.get(CONF_SHOW_TOPN) == UNLIMITED_TOPN:
            values[CONF_SHOW_TOPN] = DEFAULT_TOPN
            _LOGGER.info(
                "Feed %s: show_topn was the old default of %s and is now %s. "
                "Set it back under the integration's options if you want more "
                "entries",
                entry.title,
                UNLIMITED_TOPN,
                DEFAULT_TOPN,
            )

    hass.config_entries.async_update_entry(
        entry,
        data=data,
        options=options,
        version=CONFIG_ENTRY_VERSION,
    )
    return True
