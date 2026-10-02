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


# Home Assistant pins `feedparser` for its own `feedreader` integration, and
# hassfest rejects an exact pin of a package core ships: it would break the day
# core moves on. Those get a minimum at core's version instead.
SHIPPED_BY_CORE = {"feedparser"}
REQUIREMENT = re.compile(r"^([A-Za-z0-9_.-]+)(==|>=)(.+)$")


def manifest_requirements() -> dict[str, tuple[str, str]]:
    """Return the manifest requirements as name -> (operator, version)."""
    parsed = {}
    for requirement in json.loads(MANIFEST.read_text())["requirements"]:
        match = REQUIREMENT.match(requirement)
        assert match, f"{requirement} names no single version"
        name, operator, version = match.groups()
        parsed[name] = (operator, version)
    return parsed


def test_every_requirement_names_one_version() -> None:
    """Test that each requirement is tied to one version, the right way round.

    Home Assistant installs these into the running instance, so an unbounded one
    means the integration ships whatever version happens to be current at
    install time. Our own requirements are pinned exactly; a package core ships
    gets a minimum at core's version, as hassfest demands.
    """
    requirements = manifest_requirements()
    assert requirements
    for name, (operator, _) in requirements.items():
        expected = ">=" if name in SHIPPED_BY_CORE else "=="
        assert operator == expected, f"{name} should use {expected}"


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
    for name, (_, version) in manifest_requirements().items():
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
