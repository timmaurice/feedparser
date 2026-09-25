"""Diagnostics support for the Feedparser integration."""

from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

from .const import MAX_STATE_ATTRS_BYTES
from .parser import attributes_size, state_attributes

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import FeedparserConfigEntry, FeedparserCoordinator

REDACTED = "**REDACTED**"

# A path segment that is long, made only of the characters a token is made of,
# and mixes letters with digits. Private podcast feeds - Patreon, Supporting
# Cast and the like - put their per-subscriber token in the path rather than in
# the query string, as `/feeds/<token>/rss`. A readable segment such as
# `matter_energy` or `wdr-aktuell-152` does not match, so the URL stays
# recognisable; the rule errs towards redacting, because an over-redacted
# diagnostics download costs a follow-up question and a leaked one costs a feed.
TOKENISH_SEGMENT = re.compile(
    r"^(?=[\w=-]*\d)(?=[\w=-]*[A-Za-z])[A-Za-z0-9_=-]{16,}$",
)


def redact_path(path: str) -> str:
    """Return a URL path with the segments that look like a secret removed."""
    return "/".join(
        REDACTED if TOKENISH_SEGMENT.match(segment) else segment
        for segment in path.split("/")
    )


def redact_url(url: str) -> str:
    """Return a feed URL without the parts that can carry a secret.

    A diagnostics download tends to end up in a GitHub issue, and a private
    feed URL carries its token in the query string, in the userinfo or - which
    is what a private podcast feed does - in the path. The rest of the path is
    what makes the URL recognisable, so that is kept.
    """
    split = urlsplit(url)
    netloc = f"{REDACTED}@{split.hostname}" if split.username else split.netloc
    return urlunsplit(
        (
            split.scheme,
            netloc,
            redact_path(split.path),
            REDACTED if split.query else "",
            "",
        ),
    )


def attribute_size(coordinator: FeedparserCoordinator) -> int | None:
    """Return the size of the state attributes the sensor would write."""
    if coordinator.data is None:
        return None
    return attributes_size(
        state_attributes(
            coordinator.config.feed_url,
            coordinator.data.channel,
            coordinator.data.entries,
        ),
    )


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,  # noqa: ARG001
    entry: FeedparserConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    What a report about this integration needs: the settings in effect, and
    enough about the last poll to tell a feed that is not being fetched from
    one whose entries are being filtered away or dropped by the recorder.

    An entry whose setup failed has no coordinator, and that is the entry a
    report is most likely to be downloaded for. Reading its coordinator
    unguarded turned "Download diagnostics" into a traceback; what is known
    about such an entry - its stored settings - is reported instead.

    Such an entry has no `runtime_data` attribute at all rather than one that
    is None: setup only assigns it after the first refresh succeeded, and Home
    Assistant deletes it again on unload. Reading it plainly would raise an
    AttributeError, so it is read with a default.
    """
    coordinator: FeedparserCoordinator | None = getattr(entry, "runtime_data", None)
    entry_report = {
        "version": entry.version,
        "data": {
            key: redact_url(value) if key == "feed_url" else value
            for key, value in entry.data.items()
        },
        "options": dict(entry.options),
    }
    if coordinator is None:
        return {
            "entry": entry_report,
            "setup": "The entry is not set up, so there is no poll to report.",
        }

    config = dataclasses.asdict(coordinator.config)
    config["feed_url"] = redact_url(config["feed_url"])
    parsed = coordinator.data
    size = attribute_size(coordinator)

    return {
        "entry": entry_report,
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
