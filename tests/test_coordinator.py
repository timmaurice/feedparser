"""Tests the coordinator's poll: fetch, parse, and what a failed poll keeps."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

from constants import DATE_FORMAT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import frame

from custom_components.feedparser.coordinator import FeedparserCoordinator
from custom_components.feedparser.parser import FeedParserConfig

if TYPE_CHECKING:
    from pathlib import Path

FEED = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Feed</title>
  <item><title>First</title><link>https://ex.com/1</link></item>
  <item><title>Second</title><link>https://ex.com/2</link></item>
</channel></rss>"""

CHALLENGE_PAGE = b"""<!DOCTYPE html><html><head><title>Just a moment...</title></head>
<body><h1>Checking your browser before accessing ex.com</h1></body></html>"""


def test_a_page_that_is_not_a_feed_keeps_the_last_entries(tmp_path: Path) -> None:
    """Test that a 200 with a challenge page fails the poll instead of emptying it.

    A Cloudflare challenge, a captive portal or an empty body is served with a
    200, so only the parser can tell it is not a feed. Parsed as one, it set
    the sensor to 0 entries without `stale`; a failed poll keeps the last ones.
    """
    feed = tmp_path / "feed.xml"

    async def run() -> tuple[int, bool, int]:
        hass = HomeAssistant(str(tmp_path))
        frame.async_setup(hass)
        hass.config.allowlist_external_dirs = {str(tmp_path)}
        coordinator = FeedparserCoordinator(
            hass,
            FeedParserConfig(
                feed_url=feed.as_uri(),
                name="Feed",
                date_format=DATE_FORMAT,
                show_topn=5,
            ),
            update_interval=timedelta(hours=1),
        )
        feed.write_bytes(FEED)
        await coordinator.async_refresh()
        good = len(coordinator.data.entries)
        feed.write_bytes(CHALLENGE_PAGE)
        await coordinator.async_refresh()
        success, kept = coordinator.last_update_success, len(coordinator.data.entries)
        await hass.async_stop(force=True)
        return good, success, kept

    good, success, kept = asyncio.run(run())
    assert good == 2  # noqa: PLR2004
    assert success is False
    assert kept == 2  # noqa: PLR2004
