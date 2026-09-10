"""Fetching of feed content."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import REQUEST_HEADERS, REQUEST_TIMEOUT

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class FeedparserApiError(Exception):
    """Raised when a feed cannot be fetched."""


class FeedparserAPI:
    """Fetches raw feed content over HTTP(S) or from a local file."""

    def __init__(self: FeedparserAPI, hass: HomeAssistant) -> None:
        """Initialize the API client."""
        self.hass = hass

    async def async_fetch(self: FeedparserAPI, url: str) -> bytes:
        """Return the raw content of a feed.

        `file://` URLs are read from disk in the executor; everything else goes
        through Home Assistant's shared aiohttp session.
        """
        if urlparse(url).scheme == "file":
            return await self._async_read_file(url)
        return await self._async_get(url)

    async def _async_get(self: FeedparserAPI, url: str) -> bytes:
        """Fetch a feed over HTTP(S)."""
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                url,
                headers=REQUEST_HEADERS,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                response.raise_for_status()
                return await response.read()
        except (aiohttp.ClientError, TimeoutError, asyncio.TimeoutError) as err:
            msg = f"Error fetching feed from {url}: {err}"
            raise FeedparserApiError(msg) from err

    async def _async_read_file(self: FeedparserAPI, url: str) -> bytes:
        """Read a feed from a local `file://` URL."""
        path = Path(unquote(urlparse(url).path))
        try:
            return await self.hass.async_add_executor_job(path.read_bytes)
        except OSError as err:
            msg = f"Error reading feed from {path}: {err}"
            raise FeedparserApiError(msg) from err
