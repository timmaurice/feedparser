"""Tests the canary's reading of a feed (scripts/canary.py) on the recordings.

The canary compares a live feed with the recorded one, so what it concludes
from the recordings alone has to hold: a recording is never different from
itself, and a feed that has lost what the recording always had is.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from live_feeds import fingerprint, recorded, vanished

if TYPE_CHECKING:
    from feedsource import FeedSource


def test_a_recording_has_what_a_card_shows(feed: FeedSource) -> None:
    """Title, link and date are in every entry of every recorded feed."""
    fixture = recorded(feed)
    assert fixture.entries
    assert {"title", "link", "published"} <= fixture.sensor_keys
    assert {"title", "link"} <= fixture.raw_keys
    assert "title" in fixture.channel_keys


def test_a_recording_has_lost_nothing_against_itself(feed: FeedSource) -> None:
    """The same feed twice is not a change, so the canary stays quiet."""
    fixture = recorded(feed)
    assert vanished(fixture, fixture) == []


def test_media_the_feed_declares_is_in_every_entry(feed: FeedSource) -> None:
    """A feed declared to have images or audio has them, or the canary is blind."""
    fixture = recorded(feed)
    if feed.has_audio:
        assert "audio" in fixture.sensor_keys


def test_a_feed_that_renamed_its_titles_is_a_change(feed: FeedSource) -> None:
    """Entries that no longer have `<title>` are what the canary is there for."""
    changed = re.sub(rb"<(/?)title>", rb"<\1heading>", feed.path.read_bytes())

    problems = vanished(recorded(feed), fingerprint(feed, changed))

    assert any("'title'" in problem for problem in problems), problems


def test_a_feed_that_lost_its_links_is_a_change(feed: FeedSource) -> None:
    """Likewise for the link of an entry."""
    changed = re.sub(rb"<(/?)link>", rb"<\1url>", feed.path.read_bytes())

    problems = vanished(recorded(feed), fingerprint(feed, changed))

    assert any("'link'" in problem for problem in problems), problems


def test_a_page_that_is_not_a_feed_has_no_entries(feed: FeedSource) -> None:
    """A moved feed often answers with an HTML page, not with an error."""
    page = b"<!doctype html><html><body><h1>Not found</h1></body></html>"

    assert fingerprint(feed, page).entries == 0
