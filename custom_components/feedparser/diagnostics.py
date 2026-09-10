"""Diagnostics support for the Feedparser integration."""

from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

from .const import DOMAIN, MAX_STATE_ATTRS_BYTES

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .coordinator import FeedparserCoordinator

REDACTED = "**REDACTED**"


def redact_url(url: str) -> str:
    """Return a feed URL without the parts that can carry a secret.

    A diagnostics download tends to end up in a GitHub issue, and a private
    feed URL carries its token in the query string or in the userinfo. The path
    is what makes the URL recognisable, so that is kept.
    """
    split = urlsplit(url)
    netloc = f"{REDACTED}@{split.hostname}" if split.username else split.netloc
    return urlunsplit(
        (
            split.scheme,
            netloc,
            split.path,
            REDACTED if split.query else "",
            "",
        ),
    )


def attribute_size(coordinator: FeedparserCoordinator) -> int | None:
    """Return the size of the state attributes the sensor would write."""
    if coordinator.data is None:
        return None
    attributes = {
        "channel": coordinator.data.channel,
        "entries": coordinator.data.entries,
    }
    return len(json.dumps(attributes, default=str).encode())


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    What a report about this integration needs: the settings in effect, and
    enough about the last poll to tell a feed that is not being fetched from
    one whose entries are being filtered away or dropped by the recorder.
    """
    coordinator: FeedparserCoordinator = hass.data[DOMAIN][entry.entry_id]
    config = dataclasses.asdict(coordinator.config)
    config["feed_url"] = redact_url(config["feed_url"])
    parsed = coordinator.data
    size = attribute_size(coordinator)

    return {
        "entry": {
            "version": entry.version,
            "data": {
                key: redact_url(value) if key == "feed_url" else value
                for key, value in entry.data.items()
            },
            "options": dict(entry.options),
        },
        "parser_config": config,
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval_minutes": (
                coordinator.update_interval.total_seconds() / 60
                if coordinator.update_interval
                else None
            ),
        },
        "feed": {
            "has_data": parsed is not None,
            "state": parsed.native_value if parsed else None,
            "entry_count": len(parsed.entries) if parsed else 0,
            "channel_keys": sorted(parsed.channel) if parsed else [],
            # The keys, not the values: a diagnostics download is meant to be
            # readable and shareable, and the entries are the part that is
            # neither - they are also already visible on the entity.
            "entry_keys": (
                sorted({key for e in parsed.entries for key in e}) if parsed else []
            ),
            "state_attributes_bytes": size,
            "recorder_limit_bytes": MAX_STATE_ATTRS_BYTES,
            "exceeds_recorder_limit": (
                size > MAX_STATE_ATTRS_BYTES if size is not None else None
            ),
        },
    }
