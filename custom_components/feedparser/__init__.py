"""A component which allows you to parse an RSS feed into a sensor."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import Platform

from .const import (
    CONF_EXCLUSIONS,
    CONF_INCLUSIONS,
    CONF_SHOW_TOPN,
    DEFAULT_TOPN,
    DOMAIN,
    UNLIMITED_TOPN,
    as_field_list,
)
from .coordinator import build_coordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

# The entry version each migration step was introduced with, so an entry that
# skipped a release gets every step it missed and none it already had.
SHOW_TOPN_CAPPED_VERSION = 2
FIELD_LISTS_VERSION = 3
CONFIG_ENTRY_VERSION = FIELD_LISTS_VERSION


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


def _migrate_show_topn(entry: ConfigEntry, values: dict[str, Any]) -> None:
    """Replace the old materialised show_topn default with the new one.

    Version 1 entries were written by a config flow whose form default was
    UNLIMITED_TOPN, and voluptuous materialised that default into the stored
    data even when the user never touched the field. Such an entry keeps every
    entry of its feed and pushes the state attributes past what the recorder
    stores, so move it onto the new default. Any other number is a value
    somebody chose and is left alone.
    """
    if values.get(CONF_SHOW_TOPN) != UNLIMITED_TOPN:
        return
    values[CONF_SHOW_TOPN] = DEFAULT_TOPN
    _LOGGER.info(
        "Feed %s: show_topn was the old default of %s and is now %s. "
        "Set it back under the integration's options if you want more entries",
        entry.title,
        UNLIMITED_TOPN,
        DEFAULT_TOPN,
    )


def _migrate_field_lists(values: dict[str, Any]) -> None:
    """Turn comma separated inclusions/exclusions into lists.

    The options form used a text field and stored what was typed - `"title,
    published"` - while YAML and the entry data held a list, so the coordinator
    had to reinterpret the string on every poll. The picker stores a list now;
    converting the stored value here is what keeps an existing entry filtering
    exactly as it did.
    """
    for key in (CONF_INCLUSIONS, CONF_EXCLUSIONS):
        if key in values:
            values[key] = as_field_list(values[key])


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate an old config entry."""
    if entry.version >= CONFIG_ENTRY_VERSION:
        return True

    data = dict(entry.data)
    options = dict(entry.options)
    for values in (data, options):
        if entry.version < SHOW_TOPN_CAPPED_VERSION:
            _migrate_show_topn(entry, values)
        if entry.version < FIELD_LISTS_VERSION:
            _migrate_field_lists(values)

    hass.config_entries.async_update_entry(
        entry,
        data=data,
        options=options,
        version=CONFIG_ENTRY_VERSION,
    )
    return True
