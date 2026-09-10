"""Tests the HTML the integration hands to a dashboard.

`summary`, `content` and `subtitle` are rendered with `unsafeHTML` by the
rss-accordion card, and `title` and `author` sit in the same card, so what the
allow-list lets through is a contract of this integration. These tests are what
says so out loud - per feed dialect, because the dialect is what used to decide
whether anything was sanitised at all.
"""

from __future__ import annotations

import feedparser
import pytest

from custom_components.feedparser.const import NO_TEXT_LIMIT
from custom_components.feedparser.parser import FeedParserConfig, parse_feed

# The same payload in every dialect: an element, an attribute and a URL scheme
# the allow-list rejects, next to text that has to survive.
HOSTILE_MARKUP = (
    "<p>Real text.<script>alert(1)</script>"
    "<img src='x' onerror='steal()'>"
    '<a href="javascript:evil()">click</a></p>'
)
ESCAPED_MARKUP = (
    HOSTILE_MARKUP.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
)

RSS_FEED = f"""<?xml version="1.0"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
  <title>{ESCAPED_MARKUP}</title>
  <description>{ESCAPED_MARKUP}</description>
  <item>
    <title>{ESCAPED_MARKUP}</title>
    <dc:creator>{ESCAPED_MARKUP}</dc:creator>
    <description>{ESCAPED_MARKUP}</description>
  </item>
</channel></rss>
"""

RSS_CDATA_FEED = f"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>CDATA</title>
  <item>
    <title>Nasty</title>
    <description><![CDATA[{HOSTILE_MARKUP}]]></description>
  </item>
</channel></rss>
"""

ATOM_TEXT_FEED = f"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title type="text">{ESCAPED_MARKUP}</title>
  <subtitle type="text">{ESCAPED_MARKUP}</subtitle>
  <entry>
    <title type="text">{ESCAPED_MARKUP}</title>
    <author><name>{ESCAPED_MARKUP}</name></author>
    <summary type="text">{ESCAPED_MARKUP}</summary>
    <content type="text">{ESCAPED_MARKUP}</content>
  </entry>
</feed>
"""

ATOM_HTML_FEED = f"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Html typed</title>
  <subtitle type="html">{ESCAPED_MARKUP}</subtitle>
  <entry>
    <title>Nasty</title>
    <summary type="html">{ESCAPED_MARKUP}</summary>
  </entry>
</feed>
"""

# What must never come out, whatever the value was declared as.
FORBIDDEN = ("<script", "alert(1)", "onerror", "steal()", "javascript:")


def config(**overrides: object) -> FeedParserConfig:
    """Return a config that keeps every key and the full text."""
    defaults: dict[str, object] = {
        "feed_url": "https://example.com/feed.xml",
        "name": "hostile",
        "date_format": "%a, %d %b %Y %H:%M:%S",
        "show_topn": 5,
        "max_text_length": NO_TEXT_LIMIT,
    }
    return FeedParserConfig(**(defaults | overrides))  # type: ignore[arg-type]


def rendered(value: object) -> str:
    """Return everything a card could render out of one attribute value."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(rendered(item) for item in value)
    if isinstance(value, dict):
        return "".join(rendered(item) for item in value.values())
    return ""


def assert_clean(value: object) -> None:
    """Assert that nothing the allow-list rejects survives in a value."""
    text = rendered(value)
    for forbidden in FORBIDDEN:
        assert forbidden not in text, f"{forbidden!r} survived in {text!r}"


@pytest.mark.parametrize(
    ("feed_xml", "keys"),
    [
        pytest.param(RSS_FEED, ("summary", "title", "author"), id="rss_escaped"),
        pytest.param(RSS_CDATA_FEED, ("summary",), id="rss_cdata"),
        pytest.param(
            ATOM_TEXT_FEED,
            ("summary", "content", "title", "author"),
            id="atom_text",
        ),
        pytest.param(ATOM_HTML_FEED, ("summary",), id="atom_html"),
    ],
)
def test_hostile_markup_is_stripped_in_every_dialect(
    feed_xml: str,
    keys: tuple[str, ...],
) -> None:
    """Test that no feed dialect can put a script into a rendered attribute.

    Only values a feed declares as HTML go through feedparser's own allow-list.
    An Atom `<summary type="text">`, an RSS `<title>` and an `<author>` are
    declared as text, and their escaped markup used to be unescaped and handed
    over live.
    """
    parsed = parse_feed(feed_xml, config())
    entry = parsed.entries[0]
    for key in keys:
        assert key in entry, f"{key} missing from {sorted(entry)}"
        assert_clean(entry[key])
    assert "Real text." in rendered(entry["summary"])


def test_the_channel_is_sanitised_too() -> None:
    """Test that the feed level values a card shows are covered as well."""
    for feed in (RSS_FEED, ATOM_TEXT_FEED, ATOM_HTML_FEED):
        channel = parse_feed(feed, config()).channel
        assert_clean(channel)


def test_every_attribute_of_a_hostile_feed_is_clean() -> None:
    """Test the whole payload, not just the keys named in the contract.

    A feed can put its markup into any element it likes, and the card is not
    the only consumer - a template reading an attribute nobody thought of gets
    the same treatment.
    """
    for feed in (RSS_FEED, RSS_CDATA_FEED, ATOM_TEXT_FEED, ATOM_HTML_FEED):
        parsed = parse_feed(feed, config())
        assert_clean(parsed.channel)
        for entry in parsed.entries:
            assert_clean(entry)


def test_sanitising_does_not_depend_on_the_feedparser_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that another component turning SANITIZE_HTML off changes nothing.

    `feedparser.SANITIZE_HTML` is a process global and 6.0.x has no per call
    override, so anything else in the Home Assistant process can switch it off.
    The contract has to hold without it, which is why this integration
    sanitises its own output instead of relying on the flag.
    """
    monkeypatch.setattr(feedparser, "SANITIZE_HTML", False)
    for feed in (RSS_FEED, RSS_CDATA_FEED, ATOM_TEXT_FEED, ATOM_HTML_FEED):
        parsed = parse_feed(feed, config())
        assert_clean(parsed.channel)
        for entry in parsed.entries:
            assert_clean(entry)


UNSAFE_URL_FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Unsafe links</title>
  <item>
    <title>Nasty</title>
    <link>javascript:alert(1)</link>
    <enclosure url=" javascript:alert(2)" type="image/png"/>
  </item>
</channel></rss>
"""


def test_a_url_the_allow_list_rejects_does_not_reach_the_card() -> None:
    """Test that `link` and `image` cannot carry a script URL.

    They are rendered as an `href` and a `src`, so a `javascript:` URL there is
    the same hole as one inside the summary - and the leading space in the
    enclosure is what walks a raw scheme check past it.
    """
    entry = parse_feed(UNSAFE_URL_FEED, config()).entries[0]
    assert "javascript:" not in rendered(entry)
    assert entry.get("link", "") == ""
    assert entry.get("image", "") == ""
