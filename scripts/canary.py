"""Canary: run the integration's parser against the live feeds.

    python scripts/canary.py

The unit tests run on feeds as they were recorded (tests/data), so they stay
green when a publisher changes its feed. This is the check that does not: it
fetches every feed the suite records, reads it with the same sensor
configuration, and fails loudly when the parser finds nothing, or when a field
that the recorded feed had in every entry (a title, an image, an enclosure) is
gone from the live one. The second part catches the change the parser happens
to survive: an image that quietly stops arriving is still a feed that parses.

Exit status: 0 all fine, 1 a feed's format changed (or nothing was found in it),
2 a feed could not be fetched, which says nothing about its format.
Runs weekly in .github/workflows/canary.yml. When it fails because a format
moved, fix the parser, then `python scripts/refresh_fixtures.py <name>`.
"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

from live_feeds import (
    FEEDS,
    fetch_all,
    fingerprint,
    recorded,
    vanished,
)

if TYPE_CHECKING:
    from feedsource import FeedSource


def check(feed: FeedSource, content: bytes) -> list[str]:
    """Return what is wrong with the live feed `content`, as read for `feed`."""
    live = fingerprint(feed, content)
    print(f"{feed.name}: {live.entries} entries, keys {sorted(live.sensor_keys)}")
    if not live.entries:
        return ["no entries found, the URL answers with something that is not a feed"]
    return vanished(recorded(feed), live)


async def main() -> int:
    """Check every feed and return the exit status."""
    failures: list[str] = []
    unreachable: list[str] = []

    for feed, result in zip(FEEDS, await fetch_all(FEEDS), strict=True):
        if isinstance(result, BaseException):
            print(f"{feed.name}: not fetched - {result}")
            unreachable.append(f"{feed.name}: {result}")
            continue
        for problem in check(feed, result):
            print(f"  FAIL {problem}")
            failures.append(f"{feed.name}: {problem}")

    if failures:
        print("\nCANARY FAILED - a feed's format has most likely changed:")
        for failure in failures:
            print(f"  - {failure}")
        print("\nFix the parser, then run scripts/refresh_fixtures.py <name>.")
        return 1
    if unreachable:
        print("\ncould not reach every feed, nothing is known about those formats:")
        for line in unreachable:
            print(f"  - {line}")
        return 2
    print("\nok: the parser still reads every live feed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
