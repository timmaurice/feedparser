"""Tests the feed fetching layer."""

from __future__ import annotations

import asyncio
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from custom_components.feedparser import api as api_module
from custom_components.feedparser.api import FeedparserAPI, FeedparserApiError
from custom_components.feedparser.const import FALLBACK_USER_AGENT, USER_AGENT

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from homeassistant.core import HomeAssistant


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
    return FeedparserAPI(cast("HomeAssistant", FakeHass()))


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


class FeedServer:
    """A local HTTP server that answers like the feed server in #7.

    It refuses the browser User-Agent with `browser_status` and serves a feed
    to anything else, and records the User-Agent of every request it gets.
    """

    def __init__(self: FeedServer, browser_status: int, other_status: int) -> None:
        """Remember the statuses to answer with."""
        self.browser_status = browser_status
        self.other_status = other_status
        self.user_agents: list[str] = []

    async def handle(self: FeedServer, request: web.Request) -> web.Response:
        """Answer one request."""
        user_agent = request.headers.get("User-Agent", "")
        self.user_agents.append(user_agent)
        status = self.browser_status if user_agent == USER_AGENT else self.other_status
        return web.Response(status=status, body=b"<rss/>")

    def fetch(self: FeedServer, monkeypatch: pytest.MonkeyPatch) -> bytes:
        """Fetch the served feed through FeedparserAPI."""

        async def run() -> bytes:
            app = web.Application()
            app.router.add_get("/feed.xml", self.handle)
            async with TestServer(app) as server, aiohttp.ClientSession() as session:
                monkeypatch.setattr(
                    api_module,
                    "async_get_clientsession",
                    lambda _: session,
                )
                api = FeedparserAPI(cast("HomeAssistant", FakeHass()))
                return await api.async_fetch(str(server.make_url("/feed.xml")))

        return asyncio.run(run())


def test_the_browser_user_agent_is_tried_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """A feed that accepts the browser string is fetched in one request."""
    server = FeedServer(browser_status=HTTPStatus.OK, other_status=HTTPStatus.OK)
    assert server.fetch(monkeypatch) == b"<rss/>"
    assert server.user_agents == [USER_AGENT]


def test_a_refused_browser_user_agent_is_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 403 for the browser string is retried with the fallback (#7)."""
    server = FeedServer(browser_status=HTTPStatus.FORBIDDEN, other_status=HTTPStatus.OK)
    assert server.fetch(monkeypatch) == b"<rss/>"
    assert server.user_agents == [USER_AGENT, FALLBACK_USER_AGENT]


def test_a_403_for_both_user_agents_keeps_its_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the fallback is refused too, the error says 403."""
    server = FeedServer(
        browser_status=HTTPStatus.FORBIDDEN,
        other_status=HTTPStatus.FORBIDDEN,
    )
    with pytest.raises(FeedparserApiError) as caught:
        server.fetch(monkeypatch)
    assert caught.value.status == HTTPStatus.FORBIDDEN
    assert len(server.user_agents) == 2  # noqa: PLR2004


def test_other_errors_are_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only a 403 says something about the User-Agent, a 404 does not."""
    server = FeedServer(
        browser_status=HTTPStatus.NOT_FOUND,
        other_status=HTTPStatus.OK,
    )
    with pytest.raises(FeedparserApiError) as caught:
        server.fetch(monkeypatch)
    assert caught.value.status == HTTPStatus.NOT_FOUND
    assert server.user_agents == [USER_AGENT]


def test_a_local_file_error_has_no_status(api: FeedparserAPI, tmp_path: Path) -> None:
    """Only an HTTP answer carries a status."""
    missing = (tmp_path / "nope.xml").absolute().as_uri()
    with pytest.raises(FeedparserApiError) as caught:
        asyncio.run(api.async_fetch(missing))
    assert caught.value.status is None
