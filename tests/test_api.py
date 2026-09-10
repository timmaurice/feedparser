"""Tests the feed fetching layer."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

import pytest
from homeassistant.core import HomeAssistant

from custom_components.feedparser.api import FeedparserAPI, FeedparserApiError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


class FakeHass:
    """Minimal stand-in for HomeAssistant, only needs the executor helper."""

    @staticmethod
    async def async_add_executor_job(
        target: Callable[..., object],
        *args: object,
    ) -> object:
        """Run the target in the running loop's default executor."""
        return await asyncio.get_running_loop().run_in_executor(None, target, *args)


@pytest.fixture()
def api() -> FeedparserAPI:
    """Return an API client backed by the fake hass."""
    return FeedparserAPI(cast(HomeAssistant, FakeHass()))


def test_local_feed_is_read(api: FeedparserAPI, tmp_path: Path) -> None:
    """A file:// URL is read from disk."""
    feed = tmp_path / "feed.xml"
    feed.write_bytes(b"<rss/>")
    assert asyncio.run(api.async_fetch(feed.absolute().as_uri())) == b"<rss/>"


def test_local_feed_with_spaces_is_read(api: FeedparserAPI, tmp_path: Path) -> None:
    """A percent-encoded file:// URL is decoded before reading."""
    feed = tmp_path / "my feed.xml"
    feed.write_bytes(b"<rss/>")
    url = feed.absolute().as_uri()
    assert "%20" in url
    assert asyncio.run(api.async_fetch(url)) == b"<rss/>"


def test_missing_local_feed_raises(api: FeedparserAPI, tmp_path: Path) -> None:
    """A missing file:// target raises FeedparserApiError, not OSError."""
    missing = (tmp_path / "nope.xml").absolute().as_uri()
    with pytest.raises(FeedparserApiError):
        asyncio.run(api.async_fetch(missing))
