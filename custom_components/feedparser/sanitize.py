"""Sanitising of the values this integration hands to a dashboard.

`summary`, `content` and `subtitle` are rendered as HTML by the
[rss-accordion](https://github.com/timmaurice/lovelace-rss-accordion) card,
with `unsafeHTML`, and `title`, `author` and the entry URLs end up in the same
card. Relying on `feedparser`'s own `SANITIZE_HTML` for that does not hold:
that allow-list is only applied to values the feed declares as HTML. An Atom
`<summary type="text">`, an RSS `<title>` or an `<author>` are declared as
plain text, so their escaped markup is unescaped and handed over untouched -
`&lt;script&gt;` arrives as a live `<script>`.

Every string this integration exposes therefore goes through the allow-list
here, whatever the feed dialect and whatever the process-global
`feedparser.SANITIZE_HTML` happens to be set to.
"""

from __future__ import annotations

from typing import Any

# feedparser's sanitiser is not part of its public API, which is why the
# manifest pins the version. Importing it rather than writing a second HTML
# allow-list is deliberate: this is the same allow-list the library applies to
# HTML typed values, so a feed is sanitised identically in every dialect.
from feedparser.sanitizer import _sanitize_html
from feedparser.urls import make_safe_absolute_uri

# Values under these keys are URLs, not markup. Running them through the HTML
# sanitiser would escape the `&` of a query string; they are checked against
# feedparser's scheme allow-list instead, so a `javascript:` or `data:` URL
# cannot reach the `href` or `src` a card builds from them.
URL_KEYS = frozenset({"link", "image", "audio", "href", "url"})


def sanitize_html(value: str) -> str:
    """Return `value` with everything the allow-list rejects removed."""
    if "<" not in value:
        return value
    return _sanitize_html(value, "utf-8", "text/html")


def safe_url(value: str) -> str:
    """Return `value` if it is a URL a browser may be pointed at, else "".

    The value is stripped first: `make_safe_absolute_uri` splits the scheme off
    the raw string, so a leading space is enough to walk a `javascript:` URL
    past it, while browsers ignore that whitespace.
    """
    return make_safe_absolute_uri(value.strip())


def sanitize_value(key: str, value: Any) -> Any:  # noqa: ANN401
    """Sanitise one value of an entry, recursing into lists and dicts.

    Nested values carry their own key - the `href` of a link, the `url` of a
    media item - so the URL rule applies at every depth.
    """
    if isinstance(value, str):
        return safe_url(value) if key in URL_KEYS else sanitize_html(value)
    if isinstance(value, list):
        return [sanitize_value(key, item) for item in value]
    if isinstance(value, dict):
        return {nested: sanitize_value(nested, item) for nested, item in value.items()}
    return value


def sanitize_mapping(values: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of an entry or channel with every value sanitised.

    A top level URL the allow-list rejects drops out entirely rather than
    staying behind as an empty string: `image` and `link` are read as "there is
    one", and an empty one renders as a broken image or a dead link.
    """
    sanitized: dict[str, Any] = {}
    for key, value in values.items():
        cleaned = sanitize_value(key, value)
        if key in URL_KEYS and isinstance(value, str) and value and not cleaned:
            continue
        sanitized[key] = cleaned
    return sanitized
