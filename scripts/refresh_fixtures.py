"""Refresh tests/data/ from the live feeds.

    python scripts/refresh_fixtures.py                  # rewrite every feed
    python scripts/refresh_fixtures.py ntv the_daily    # only these
    python scripts/refresh_fixtures.py --check          # change nothing, say what moved

Run it when the canary (scripts/canary.py, .github/workflows/canary.yml)
reports that a feed's format has changed and the parser has been adjusted to
it: the tests then run against the feed as it is now. Review the diff before
committing - it is the publisher's change, line by line - and run the suite.

The feed is stored byte for byte (the pre-commit hooks leave tests/data alone
for that reason) and `download_date` in its metadata is set to now. Some tests
read dates relative to it, so a refreshed feed may need its expectations
looked at. Needs network access and the dev dependencies (`pip install .[dev]`).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime

from live_feeds import FEEDS, fetch_all, fingerprint, recorded, vanished


async def main(names: list[str], check: bool) -> int:
    """Refresh (or with `check` only compare) the feeds, return the exit status."""
    known = {feed.name: feed for feed in FEEDS}
    if unknown := [name for name in names if name not in known]:
        print(f"unknown feed(s): {', '.join(unknown)}; known: {', '.join(known)}")
        return 2

    feeds = [known[name] for name in names] if names else FEEDS
    status = 0
    for feed, result in zip(feeds, await fetch_all(feeds), strict=True):
        if isinstance(result, BaseException):
            print(f"{feed.name}: not fetched - {result}")
            status = 1
            continue
        live = fingerprint(feed, result)
        if not live.entries:
            print(f"{feed.name}: no entries in what was fetched - kept as it was.")
            status = 1
            continue

        gone = vanished(recorded(feed), live)
        print(f"{feed.name}: {live.entries} entries, {len(gone)} fields gone")
        for problem in gone:
            print(f"    - {problem}")

        if check:
            continue
        feed.path.write_bytes(result)
        metadata = dict(feed.metadata)
        metadata["download_date"] = datetime.now(UTC).astimezone().isoformat()
        feed.metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
        print(f"{feed.name}: written")
    return status


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="*", help="feeds by name (default: all)")
    parser.add_argument("--check", action="store_true", help="only report")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.names, args.check)))
