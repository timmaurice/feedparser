"""Tests the integration manifest."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "custom_components/feedparser/manifest.json"
PYPROJECT = ROOT / "pyproject.toml"
SENSOR = ROOT / "custom_components/feedparser/sensor.py"

# The manifest is what Home Assistant installs from; `pyproject.toml` is what
# the test environment and CI install from. A requirement pinned in one and
# floating in the other means the suite is not exercising what users get.
PYPROJECT_DEPENDENCIES = re.compile(r"^dependencies = \[(.*?)^\]", re.M | re.S)
QUOTED = re.compile(r'"([^"]+)"')


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


def pyproject_dependencies() -> list[str]:
    """Return the runtime dependencies declared in `pyproject.toml`."""
    block = PYPROJECT_DEPENDENCIES.search(PYPROJECT.read_text())
    assert block is not None
    return QUOTED.findall(block.group(1))


def test_pyproject_pins_what_the_manifest_pins() -> None:
    """Test that both dependency lists agree on the version.

    `python-dateutil` was pinned in the manifest and left floating here, so the
    version the suite ran against was not the version the integration ships -
    which is what "verified against the pinned version" is supposed to mean.
    """
    declared = dict(
        dependency.split("==", 1)
        for dependency in pyproject_dependencies()
        if "==" in dependency
    )
    unpinned = [
        dependency
        for dependency in pyproject_dependencies()
        # Home Assistant is the host, not something this integration installs.
        if "==" not in dependency and dependency != "homeassistant"
    ]
    assert unpinned == []
    for requirement in json.loads(MANIFEST.read_text())["requirements"]:
        name, version = requirement.split("==", 1)
        assert declared.get(name) == version, f"{name} disagrees with the manifest"


def test_the_version_is_the_same_in_all_three_places() -> None:
    """Test that a release bump reached every file that carries the version.

    `bumpver` writes all three, and a bump applied by hand does not: the
    manifest said 1.2.0 while `pyproject.toml` and `sensor.py` still said
    1.1.0, which is the version HACS shows against the version a bug report
    quotes.
    """
    manifest_version = json.loads(MANIFEST.read_text())["version"]
    pyproject = PYPROJECT.read_text()
    assert f'version = "{manifest_version}"' in pyproject
    assert f'current_version = "{manifest_version}"' in pyproject
    assert f'__version__ = "{manifest_version}"' in SENSOR.read_text()
