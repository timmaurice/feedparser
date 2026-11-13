"""What the canary and the fixture refresh share: fetching and fingerprints.

A fixture is a feed as it was when it was recorded (tests/data/<name>.xml, with
the sensor configuration it is read with in <name>.json). The fingerprint is
what the canary compares: which fields the feed's entries carry, as feedparser
reads them and as the sensor exposes them.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path

import aiohttp
import feedparser

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from constants import DATA_PATH, TEST_FEEDS  # noqa: E402
from feedsource import FeedSource  # noqa: E402

from custom_components.feedparser.const import (  # noqa: E402
    FALLBACK_USER_AGENT,
    REQUEST_HEADERS,
)
from custom_components.feedparser.parser import (  # noqa: E402
    FeedParserConfig,
    parse_feed,
)

FEEDS = [FeedSource(feed) for feed in TEST_FEEDS]
FIXTURES = DATA_PATH

# A key the recorded feed has in every entry has to be in at least this share of
# the live feed's entries. Not every entry: one article without a picture is
# editorial, every article without one is a changed feed.
KEPT_SHARE = 0.5


class FetchError(Exception):
    """The feed could not be fetched; that says nothing about its format."""


@dataclass(frozen=True)
class Fingerprint:
    """The fields a feed's entries carry, and how many entries there are."""

    entries: int
    channel_keys: frozenset[str]
    # Keys in all of the entries, as feedparser reads them and as the sensor
    # exposes them.
    raw_keys: frozenset[str]
    sensor_keys: frozenset[str]
    # How many of the entries each key is in, for the share the canary asks for.
    raw_counts: dict[str, int]
    sensor_counts: dict[str, int]


def _counts(entries: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        for key, value in entry.items():
            if value not in (None, "", [], {}):
                counts[key] = counts.get(key, 0) + 1
    return counts


def _in_all(counts: dict[str, int], total: int) -> frozenset[str]:
    return frozenset(key for key, n in counts.items() if n == total)


def config_for(feed: FeedSource, url: str | None = None) -> FeedParserConfig:
    """Return the configuration the feed is read with, for its live URL if given."""
    kwargs = feed.parser_config_local_feed
    if url:
        kwargs = kwargs | {"feed_url": url}
    return FeedParserConfig(**kwargs)  # type: ignore[arg-type]


def fingerprint(feed: FeedSource, content: bytes) -> Fingerprint:
    """Read `content` the way the sensor does and note what is in it."""
    raw = feedparser.parse(content)
    sensor = parse_feed(content, config_for(feed))
    raw_counts = _counts(list(raw.entries))
    sensor_counts = _counts(list(sensor.entries))
    return Fingerprint(
        entries=len(sensor.entries),
        channel_keys=frozenset(sensor.channel or {}),
        raw_keys=_in_all(raw_counts, len(raw.entries)),
        sensor_keys=_in_all(sensor_counts, len(sensor.entries)),
        raw_counts=raw_counts,
        sensor_counts=sensor_counts,
    )


def vanished(recorded: Fingerprint, live: Fingerprint) -> list[str]:
    """Return what the recorded feed always had and the live one no longer has."""
    problems: list[str] = []
    for what, keys, counts, total in (
        ("raw", recorded.raw_keys, live.raw_counts, live.entries),
        ("sensor", recorded.sensor_keys, live.sensor_counts, live.entries),
    ):
        for key in sorted(keys):
            if counts.get(key, 0) < max(total * KEPT_SHARE, 1):
                problems.append(
                    f"{what} key {key!r} is in {counts.get(key, 0)} of {total} "
                    "entries now, the recorded feed has it in all",
                )
    for key in sorted(recorded.channel_keys - live.channel_keys):
        problems.append(f"channel key {key!r} is gone")
    return problems


def recorded(feed: FeedSource) -> Fingerprint:
    """Return the fingerprint of the feed's fixture."""
    return fingerprint(feed, feed.path.read_bytes())


async def _get(session: aiohttp.ClientSession, url: str, headers: dict) -> bytes:
    # Not br: the job should not depend on whether a brotli decoder is installed.
    headers = {**headers, "Accept-Encoding": "gzip, deflate"}
    async with session.get(url, headers=headers) as response:
        response.raise_for_status()
        return await response.read()


async def fetch(session: aiohttp.ClientSession, url: str) -> bytes:
    """Fetch a feed the way the integration does, with its 403 retry."""
    try:
        try:
            return await _get(session, url, REQUEST_HEADERS)
        except aiohttp.ClientResponseError as err:
            if err.status != HTTPStatus.FORBIDDEN:
                raise
        return await _get(
            session,
            url,
            {**REQUEST_HEADERS, "User-Agent": FALLBACK_USER_AGENT},
        )
    except (aiohttp.ClientError, TimeoutError) as err:
        msg = f"{url}: {err}"
        raise FetchError(msg) from err


def make_session() -> aiohttp.ClientSession:
    """Return a session with a timeout that fits a weekly job."""
    return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))


async def fetch_all(
    feeds: list[FeedSource],
) -> list[bytes | FetchError]:
    """Fetch the live feeds side by side; a failed one is returned, not raised."""
    async with make_session() as session:
        return await asyncio.gather(
            *(fetch(session, feed.url) for feed in feeds),
            return_exceptions=True,
        )  # type: ignore[return-value]
