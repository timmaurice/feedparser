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

DEFAULT_DATE_FORMAT = "%a, %b %d %Y %I:%M %p"
DEFAULT_SCAN_INTERVAL = timedelta(hours=1)
DEFAULT_TOPN = 9999

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
