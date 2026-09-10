"""Constants for the Feedparser integration."""

from __future__ import annotations

import logging
from datetime import timedelta

DOMAIN = "feedparser"

CONF_FEED_URL = "feed_url"
CONF_DATE_FORMAT = "date_format"
CONF_LOCAL_TIME = "local_time"
CONF_INCLUSIONS = "inclusions"
CONF_EXCLUSIONS = "exclusions"
CONF_SHOW_TOPN = "show_topn"
CONF_REMOVE_SUMMARY_IMG = "remove_summary_image"
CONF_MAX_TEXT_LENGTH = "max_text_length"

DEFAULT_DATE_FORMAT = "%a, %b %d %Y %I:%M %p"
DEFAULT_SCAN_INTERVAL = timedelta(hours=1)
# The recorder refuses to store a state whose attributes are larger than this
# (homeassistant.components.recorder.db_schema.MAX_STATE_ATTRS_BYTES).
MAX_STATE_ATTRS_BYTES = 16384

# Everything the sensor exposes ends up in those attributes, so keep the default
# small - an unbounded default made the recorder reject the state on every poll.
# Users who want more entries can still raise show_topn.
DEFAULT_TOPN = 5

# The number the old default stood for: "keep every entry the feed offers". It
# is still what a YAML sensor without an explicit show_topn gets, and config
# entries carrying it were never given that value deliberately - the config flow
# materialised its own default into the entry - so the migration replaces it.
UNLIMITED_TOPN = 9999

# Fewer than one entry is not a feed anybody wants to look at, and a negative
# number used to slice the entry list from the end.
MIN_TOPN = 1

# Feed entries carry whole articles in `summary`/`content`. Cut the text at this
# many characters so a default sized feed stays well below the recorder limit.
# Set max_text_length to NO_TEXT_LIMIT to keep the full text.
DEFAULT_MAX_TEXT_LENGTH = 250
NO_TEXT_LIMIT = 0
TRUNCATION_SUFFIX = "..."

# Values under these keys are URLs or identifiers - enclosure URLs in particular
# get long, and a truncated one is a broken one.
UNTRUNCATED_KEYS = frozenset(
    {"link", "image", "audio", "href", "url", "id", "guid"},
)

# UI configured entries store the scan interval as a plain number of minutes.
DEFAULT_SCAN_INTERVAL_MINUTES = int(DEFAULT_SCAN_INTERVAL.total_seconds() // 60)
MIN_SCAN_INTERVAL_MINUTES = 1
MAX_SCAN_INTERVAL_MINUTES = 10080  # one week

IMAGE_REGEX = r"<img.+?src=\"(.+?)\".+?>"

REQUEST_TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

_LOGGER = logging.getLogger(__name__)


def scan_interval_from_minutes(value: str | int | float | None) -> timedelta:
    """Convert a stored scan interval in minutes into a timedelta."""
    try:
        minutes = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        _LOGGER.warning(
            "Invalid scan interval %s, falling back to %s minutes",
            value,
            DEFAULT_SCAN_INTERVAL_MINUTES,
        )
        minutes = DEFAULT_SCAN_INTERVAL_MINUTES
    minutes = min(max(minutes, MIN_SCAN_INTERVAL_MINUTES), MAX_SCAN_INTERVAL_MINUTES)
    return timedelta(minutes=minutes)
