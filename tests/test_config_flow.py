"""Tests the validation the config flow puts a feed URL through."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
import voluptuous as vol
from constants import DATA_PATH
from test_config_entry import options_schema

from custom_components.feedparser import config_flow
from custom_components.feedparser.api import FeedparserApiError
from custom_components.feedparser.config_flow import (
    STEP_USER_DATA_SCHEMA,
    async_validate_feed,
)
from custom_components.feedparser.const import CONF_SHOW_TOPN, MIN_TOPN
from custom_components.feedparser.parser import is_parsable_feed

if TYPE_CHECKING:
    from collections.abc import Callable

FEED_URL = "https://example.com/feed.xml"
A_REAL_FEED = DATA_PATH / "ntv.xml"
# What a plain web page looks like: reachable, parses, is not a feed.
AN_HTML_PAGE = b"<html><head><title>Example</title></head><body>hi</body></html>"


class FakeHass:
    """Just enough of hass for the flow's validation helper."""

    async def async_add_executor_job(
        self: FakeHass,
        target: Callable[..., Any],
        *args: Any,  # noqa: ANN401
    ) -> Any:  # noqa: ANN401
        """Run the job inline - the point is what it returns, not the thread."""
        return target(*args)


def fetching(result: bytes | Exception) -> type:
    """Return a FeedparserAPI stand-in whose fetch returns or raises `result`."""

    class FakeAPI:
        def __init__(self: FakeAPI, hass: object) -> None:
            self.hass = hass

        async def async_fetch(self: FakeAPI, url: str) -> bytes:  # noqa: ARG002
            if isinstance(result, Exception):
                raise result
            return result

    return FakeAPI


def validate(
    monkeypatch: pytest.MonkeyPatch,
    result: bytes | Exception,
) -> str | None:
    """Run the flow's validation against a fetch with the given outcome."""
    monkeypatch.setattr(config_flow, "FeedparserAPI", fetching(result))
    return asyncio.run(
        async_validate_feed(FakeHass(), FEED_URL),  # type: ignore[arg-type]
    )


def test_a_real_feed_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that a feed URL still gets through unchanged."""
    assert validate(monkeypatch, A_REAL_FEED.read_bytes()) is None


def test_a_web_page_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that a reachable page that is not a feed does not become an entry.

    It used to: the flow only checked that the URL could be fetched, so the
    entry ended up with a sensor stuck at 0 that logged "No entries found" on
    every poll.
    """
    assert validate(monkeypatch, AN_HTML_PAGE) == "invalid_feed"


def test_an_empty_response_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that an empty body is not mistaken for a feed."""
    assert validate(monkeypatch, b"") == "invalid_feed"


def test_an_unreachable_url_still_says_cannot_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that a fetch failure keeps its own error key."""
    assert validate(monkeypatch, FeedparserApiError("boom")) == "cannot_connect"


def test_an_unexpected_error_becomes_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that nothing escapes as an unhandled traceback in the flow."""
    assert validate(monkeypatch, RuntimeError("nobody saw this coming")) == "unknown"


def test_is_parsable_feed_accepts_the_fixtures() -> None:
    """Test the feed check against every feed the suite ships."""
    fixtures = sorted(DATA_PATH.glob("*.xml"))
    assert fixtures
    for fixture in fixtures:
        assert is_parsable_feed(fixture.read_bytes()), fixture.name


def user_schema() -> vol.Schema:
    """Return the schema of the add-integration form."""
    return STEP_USER_DATA_SCHEMA


def payload(schema_source: Callable[[], vol.Schema], show_topn: int) -> dict[str, Any]:
    """Return the smallest input the given form accepts, plus a show_topn."""
    required = (
        {"name": "Some Feed", "feed_url": FEED_URL}
        if schema_source is user_schema
        else {}
    )
    return {**required, CONF_SHOW_TOPN: show_topn}


@pytest.mark.parametrize("schema_source", [user_schema, options_schema])
def test_show_topn_below_one_is_rejected(
    schema_source: Callable[[], vol.Schema],
) -> None:
    """Test that the UI cannot ask for a negative or empty number of entries.

    `parse_feed` slices the entries with this value, so -5 used to slice from
    the end of the list - the sensor reported a state of -5 while carrying 254
    entries. The YAML schema uses cv.positive_int.
    """
    schema = schema_source()
    for rejected in (-5, 0):
        with pytest.raises(vol.Invalid):
            schema(payload(schema_source, rejected))


@pytest.mark.parametrize("schema_source", [user_schema, options_schema])
def test_show_topn_of_one_is_accepted(
    schema_source: Callable[[], vol.Schema],
) -> None:
    """Test that the smallest number that means something goes through."""
    validated = schema_source()(payload(schema_source, MIN_TOPN))
    assert validated[CONF_SHOW_TOPN] == MIN_TOPN
