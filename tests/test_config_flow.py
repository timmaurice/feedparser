"""Tests the validation the config flow puts a feed URL through."""

from __future__ import annotations

import asyncio
from http import HTTPStatus
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

    from homeassistant.config_entries import ConfigFlowResult

FEED_URL = "https://example.com/feed.xml"
A_REAL_FEED = DATA_PATH / "ntv.xml"
# What a plain web page looks like: reachable, parses, is not a feed.
AN_HTML_PAGE = b"<html><head><title>Example</title></head><body>hi</body></html>"
# Spelled out: what a reconfigured entry has to still be carrying afterwards.
EXPECTED_KEPT_TOPN = 5


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


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (HTTPStatus.UNAUTHORIZED, "invalid_auth"),
        (HTTPStatus.FORBIDDEN, "forbidden"),
        (HTTPStatus.NOT_FOUND, "not_found"),
        (HTTPStatus.GONE, "not_found"),
        (HTTPStatus.INTERNAL_SERVER_ERROR, "cannot_connect"),
    ],
)
def test_an_http_error_says_what_the_server_answered(
    monkeypatch: pytest.MonkeyPatch,
    status: HTTPStatus,
    error: str,
) -> None:
    """Test that a refused or missing feed is not reported as unreachable (#7)."""
    assert validate(monkeypatch, FeedparserApiError("boom", status)) == error


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


NEW_FEED_URL = "https://example.com/moved/feed.xml"
OTHER_FEED_URL = "https://elsewhere.example/feed.xml"


class FakeEntry:
    """The few attributes of a config entry the reconfigure step touches."""

    def __init__(
        self: FakeEntry,
        entry_id: str,
        data: dict[str, Any],
        unique_id: str | None = None,
    ) -> None:
        """Initialize."""
        self.entry_id = entry_id
        self.data = data
        self.unique_id = unique_id if unique_id is not None else data.get("feed_url")
        self.options: dict[str, Any] = {}
        self.source = "user"
        self.disabled_by = None


class FakeEntries:
    """Records what the reconfigure step writes back.

    Strict about the keywords it accepts for the same reason the migration's
    double is: a fake that swallows `**kwargs` would let the flow pass a
    keyword no Home Assistant takes and no test would notice.
    """

    ACCEPTED = frozenset({"data", "options", "version", "title", "unique_id"})

    def __init__(self: FakeEntries, entries: list[FakeEntry]) -> None:
        """Initialize."""
        self.entries = entries
        self.updates: list[dict[str, Any]] = []

    def async_get_entry(self: FakeEntries, entry_id: str) -> FakeEntry | None:
        """Resolve an entry the way the flow's context asks for it."""
        return next((e for e in self.entries if e.entry_id == entry_id), None)

    def async_entries(
        self: FakeEntries,
        domain: str | None = None,  # noqa: ARG002
        include_ignore: bool = True,  # noqa: ARG002, FBT002
    ) -> list[FakeEntry]:
        """Return every entry of the integration.

        Both positional arguments are spelled out because the core passes them
        that way - a fake taking only the domain fails where the real call
        would not.
        """
        return list(self.entries)

    def async_update_entry(
        self: FakeEntries,
        entry: FakeEntry,
        **kwargs: Any,  # noqa: ANN401
    ) -> bool:
        """Apply an update the way Home Assistant would."""
        if unexpected := set(kwargs) - self.ACCEPTED:
            msg = (
                "async_update_entry() got an unexpected keyword argument "
                f"{sorted(unexpected)[0]!r}"
            )
            raise TypeError(msg)
        self.updates.append(kwargs)
        entry.data = kwargs.get("data", entry.data)
        entry.unique_id = kwargs.get("unique_id", entry.unique_id)
        return True


class HassWithEntries(FakeHass):
    """The fake hass the reconfigure step needs: executor plus config entries."""

    def __init__(self: HassWithEntries, entries: list[FakeEntry]) -> None:
        """Initialize."""
        self.config_entries = FakeEntries(entries)


def reconfigure_flow(
    monkeypatch: pytest.MonkeyPatch,
    result: bytes | Exception,
    entries: list[FakeEntry],
    entry_id: str = "entry-1",
) -> tuple[config_flow.FeedparserConfigFlow, FakeEntries]:
    """Return a reconfigure flow wired to fake entries and a fixed fetch.

    Home Assistant starts this flow with the entry id in the flow context, and
    the base class carries a read-only empty mapping until it does, so the
    double has to be set directly. That is a property of running the flow
    without a flow manager, not of how the step is used.
    """
    monkeypatch.setattr(config_flow, "FeedparserAPI", fetching(result))
    flow = config_flow.FeedparserConfigFlow()
    hass = HassWithEntries(entries)
    flow.hass = hass  # type: ignore[assignment]
    flow.context = {"source": "reconfigure", "entry_id": entry_id}
    return flow, hass.config_entries


def prefilled_url(result: ConfigFlowResult) -> str:
    """Return the URL the form's field opens on."""
    data_schema = result["data_schema"]
    assert data_schema is not None, "the step showed no form"
    return data_schema({})["feed_url"]


def an_entry(url: str = FEED_URL, entry_id: str = "entry-1") -> FakeEntry:
    """Return a config entry watching `url`."""
    return FakeEntry(entry_id, {"name": "Some Feed", "feed_url": url, "show_topn": 5})


def test_reconfigure_prefills_the_url_the_entry_has(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that the form opens on the URL the feed is polled from today."""
    flow, _ = reconfigure_flow(monkeypatch, A_REAL_FEED.read_bytes(), [an_entry()])
    result = asyncio.run(flow.async_step_reconfigure())
    assert result["step_id"] == "reconfigure"
    assert prefilled_url(result) == FEED_URL


def test_reconfigure_moves_the_feed_and_its_unique_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that a new URL is stored and the entry stops claiming the old one.

    The unique id is the feed URL. Leaving it behind would let the entry go on
    claiming a URL it no longer polls, so adding the old feed again would abort
    as a duplicate while the new one could be added a second time.
    """
    entry = an_entry()
    flow, entries = reconfigure_flow(monkeypatch, A_REAL_FEED.read_bytes(), [entry])
    result = asyncio.run(flow.async_step_reconfigure({"feed_url": NEW_FEED_URL}))

    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["feed_url"] == NEW_FEED_URL
    assert entry.unique_id == NEW_FEED_URL
    assert len(entries.updates) == 1
    assert entries.updates[0]["unique_id"] == NEW_FEED_URL


def test_reconfigure_keeps_every_other_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that only the URL is rewritten.

    The step writes a whole `data` dict, so building it from anything but the
    stored one would drop the name and the settings that live beside the URL.
    """
    entry = an_entry()
    flow, _ = reconfigure_flow(monkeypatch, A_REAL_FEED.read_bytes(), [entry])
    asyncio.run(flow.async_step_reconfigure({"feed_url": NEW_FEED_URL}))
    assert entry.data["name"] == "Some Feed"
    assert entry.data["show_topn"] == EXPECTED_KEPT_TOPN


def test_reconfigure_rejects_a_url_that_is_not_a_feed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that the new URL goes through the same check as a new entry.

    Without it the reconfigure step would be a way around the validation the
    add form does - and the feed would come back as a sensor stuck at 0.
    """
    entry = an_entry()
    flow, entries = reconfigure_flow(monkeypatch, AN_HTML_PAGE, [entry])
    result = asyncio.run(flow.async_step_reconfigure({"feed_url": NEW_FEED_URL}))

    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": "invalid_feed"}
    assert entry.data["feed_url"] == FEED_URL
    assert entries.updates == []
    # the rejected URL stays in the field, so it can be corrected
    assert prefilled_url(result) == NEW_FEED_URL


def test_reconfigure_rejects_an_unreachable_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that a fetch failure keeps the entry pointed where it was."""
    entry = an_entry()
    flow, entries = reconfigure_flow(
        monkeypatch,
        FeedparserApiError("boom"),
        [entry],
    )
    result = asyncio.run(flow.async_step_reconfigure({"feed_url": NEW_FEED_URL}))

    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data["feed_url"] == FEED_URL
    assert entries.updates == []


def test_reconfigure_refuses_a_url_another_entry_watches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that two entries cannot end up on the same feed.

    A duplicate unique id is not something Home Assistant recovers from on its
    own: the second entry's entity is dropped at setup. The add form aborts on
    it, so this step has to as well - as a form error rather than an abort,
    because the user is mid-edit and can simply correct the URL.
    """
    entry = an_entry()
    other = FakeEntry("entry-2", {"name": "Other", "feed_url": OTHER_FEED_URL})
    flow, entries = reconfigure_flow(
        monkeypatch,
        A_REAL_FEED.read_bytes(),
        [entry, other],
    )
    result = asyncio.run(flow.async_step_reconfigure({"feed_url": OTHER_FEED_URL}))

    assert result["errors"] == {"base": "already_configured"}
    assert entry.data["feed_url"] == FEED_URL
    assert entries.updates == []


def test_reconfigure_accepts_the_entrys_own_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that submitting the URL unchanged is not read as a duplicate.

    `_abort_if_unique_id_configured` would have: it counts the entry being
    reconfigured. Somebody who opens the form and confirms must not be told
    their own feed is already configured.
    """
    entry = an_entry()
    flow, entries = reconfigure_flow(monkeypatch, A_REAL_FEED.read_bytes(), [entry])
    result = asyncio.run(flow.async_step_reconfigure({"feed_url": FEED_URL}))

    assert result["reason"] == "reconfigure_successful"
    assert entry.data["feed_url"] == FEED_URL
    assert entries.updates[0]["unique_id"] == FEED_URL


def test_reconfigure_of_a_deleted_entry_aborts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that a flow whose entry is gone ends instead of raising.

    An entry can be removed while its reconfigure form is open, and reading
    `entry.data` off None would reach the user as an unhandled flow traceback.
    """
    flow, _ = reconfigure_flow(monkeypatch, A_REAL_FEED.read_bytes(), [])
    result = asyncio.run(flow.async_step_reconfigure())
    assert result["type"] == "abort"
    assert result["reason"] == "unknown_entry"
