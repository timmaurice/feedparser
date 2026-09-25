"""Fetching of feed content."""

from __future__ import annotations

import logging
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import FALLBACK_USER_AGENT, REQUEST_HEADERS, REQUEST_TIMEOUT

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class FeedparserApiError(Exception):
    """Raised when a feed cannot be fetched.

    `status` is the HTTP status when the server answered with an error, and
    None when there was no answer at all, so the config flow can tell a refused
    or missing feed apart from one it could not reach.
    """

    def __init__(self: FeedparserApiError, msg: str, status: int | None = None) -> None:
        """Initialize the error."""
        super().__init__(msg)
        self.status = status


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
        """Fetch a feed over HTTP(S).

        A 403 is tried once more with FALLBACK_USER_AGENT: a server that blocks
        the browser string, for its age or because it wants no browsers, often
        lets a plainly named client through.
        """
        try:
            return await self._async_request(url, REQUEST_HEADERS)
        except aiohttp.ClientResponseError as err:
            if err.status != HTTPStatus.FORBIDDEN:
                raise self._error(url, err) from err
            _LOGGER.debug("%s refused the browser User-Agent, retrying", url)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise self._error(url, err) from err

        try:
            return await self._async_request(
                url,
                {**REQUEST_HEADERS, "User-Agent": FALLBACK_USER_AGENT},
            )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise self._error(url, err) from err

    async def _async_request(
        self: FeedparserAPI,
        url: str,
        headers: dict[str, str],
    ) -> bytes:
        """Send one GET and return the body, raising on an HTTP error status."""
        session = async_get_clientsession(self.hass)
        async with session.get(
            url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as response:
            response.raise_for_status()
            return await response.read()

    @staticmethod
    def _error(url: str, err: Exception) -> FeedparserApiError:
        """Wrap a fetch failure, keeping the HTTP status when there was one."""
        status = err.status if isinstance(err, aiohttp.ClientResponseError) else None
        return FeedparserApiError(f"Error fetching feed from {url}: {err}", status)

    async def _async_read_file(self: FeedparserAPI, url: str) -> bytes:
        """Read a feed from a local `file://` URL."""
        path = Path(unquote(urlparse(url).path))
        try:
            return await self.hass.async_add_executor_job(path.read_bytes)
        except OSError as err:
            msg = f"Error reading feed from {path}: {err}"
            raise FeedparserApiError(msg) from err
