"""Tests the integration manifest."""

from __future__ import annotations

import json
from pathlib import Path

MANIFEST = Path(__file__).parents[1] / "custom_components/feedparser/manifest.json"


def test_every_requirement_is_pinned() -> None:
    """Test that the manifest pins its requirements to an exact version.

    Home Assistant installs these into the running instance, so an unpinned one
    means the integration ships whatever version happens to be current at
    install time - and HACS validation warns about it.
    """
    requirements = json.loads(MANIFEST.read_text())["requirements"]
    assert requirements
    unpinned = [req for req in requirements if "==" not in req]
    assert unpinned == []
