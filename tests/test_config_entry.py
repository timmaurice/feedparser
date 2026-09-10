"""Tests the config entry migration and the defaults new entries are given."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import voluptuous as vol

from custom_components.feedparser import CONFIG_ENTRY_VERSION, async_migrate_entry
from custom_components.feedparser.config_flow import (
    STEP_USER_DATA_SCHEMA,
    FeedparserConfigFlow,
    FeedparserOptionsFlowHandler,
)
from custom_components.feedparser.const import (
    CONF_MAX_TEXT_LENGTH,
    CONF_SHOW_TOPN,
    DEFAULT_MAX_TEXT_LENGTH,
    DEFAULT_TOPN,
    NO_TEXT_LIMIT,
    UNLIMITED_TOPN,
)

# Spelled out on purpose: what a migrated entry has to end up with, whatever
# the constants happen to say.
OLD_MATERIALISED_TOPN = 9999
EXPECTED_TOPN = 5
EXPECTED_VERSION = 2
CHOSEN_TOPN = 20
CHOSEN_OPTION_TOPN = 40


class FakeConfigEntry:
    """The few attributes of a config entry the migration touches."""

    def __init__(
        self: FakeConfigEntry,
        data: dict[str, Any],
        options: dict[str, Any] | None = None,
        version: int = 1,
    ) -> None:
        """Initialize."""
        self.version = version
        self.data = data
        self.options = options or {}
        self.title = "Some Feed"


class FakeConfigEntries:
    """Records what the migration writes back."""

    def __init__(self: FakeConfigEntries) -> None:
        """Initialize."""
        self.updates: list[dict[str, Any]] = []

    # What `hass.config_entries.async_update_entry` accepts. Spelled out so a
    # call passing anything else - `version=` on a Home Assistant too old to
    # know it, above all - fails here instead of only in production.
    ACCEPTED = frozenset({"data", "options", "version", "title", "unique_id"})

    def async_update_entry(
        self: FakeConfigEntries,
        entry: FakeConfigEntry,
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
        entry.options = kwargs.get("options", entry.options)
        entry.version = kwargs.get("version", entry.version)
        return True


class FakeHass:
    """Just enough of hass for the migration."""

    def __init__(self: FakeHass) -> None:
        """Initialize."""
        self.config_entries = FakeConfigEntries()


def migrate(entry: FakeConfigEntry) -> FakeHass:
    """Run the migration against a fake hass and return it."""
    hass = FakeHass()
    assert asyncio.run(async_migrate_entry(hass, entry)) is True  # type: ignore[arg-type]
    return hass


def test_migration_replaces_the_old_materialised_default() -> None:
    """Test that the 9999 the old config flow stored becomes the new default."""
    entry = FakeConfigEntry(
        {"feed_url": "https://example.com", CONF_SHOW_TOPN: OLD_MATERIALISED_TOPN},
    )
    migrate(entry)
    assert entry.data[CONF_SHOW_TOPN] == EXPECTED_TOPN
    assert entry.data[CONF_SHOW_TOPN] == DEFAULT_TOPN
    assert entry.version == EXPECTED_VERSION


def test_migration_replaces_it_in_the_options_too() -> None:
    """Test that an entry carrying the old default in its options is migrated."""
    entry = FakeConfigEntry(
        {"feed_url": "https://example.com", CONF_SHOW_TOPN: OLD_MATERIALISED_TOPN},
        options={CONF_SHOW_TOPN: OLD_MATERIALISED_TOPN},
    )
    migrate(entry)
    assert entry.options[CONF_SHOW_TOPN] == EXPECTED_TOPN


def test_migration_keeps_a_value_the_user_picked() -> None:
    """Test that a number somebody chose is not overwritten."""
    entry = FakeConfigEntry(
        {"feed_url": "https://example.com", CONF_SHOW_TOPN: CHOSEN_TOPN},
        options={CONF_SHOW_TOPN: CHOSEN_OPTION_TOPN},
    )
    migrate(entry)
    assert entry.data[CONF_SHOW_TOPN] == CHOSEN_TOPN
    assert entry.options[CONF_SHOW_TOPN] == CHOSEN_OPTION_TOPN
    assert entry.version == EXPECTED_VERSION


def test_migration_leaves_current_entries_alone() -> None:
    """Test that an already migrated entry is not written again."""
    entry = FakeConfigEntry(
        {"feed_url": "https://example.com", CONF_SHOW_TOPN: UNLIMITED_TOPN},
        version=CONFIG_ENTRY_VERSION,
    )
    hass = migrate(entry)
    assert hass.config_entries.updates == []
    assert entry.data[CONF_SHOW_TOPN] == UNLIMITED_TOPN


def test_config_flow_asks_for_the_migration() -> None:
    """Test that the flow version is the one the migration produces."""
    assert FeedparserConfigFlow.VERSION == CONFIG_ENTRY_VERSION == EXPECTED_VERSION


def test_new_entries_are_created_with_the_capped_default() -> None:
    """Test that the config flow materialises the capped default, not 9999."""
    validated = STEP_USER_DATA_SCHEMA(
        {"name": "Some Feed", "feed_url": "https://example.com/feed"},
    )
    assert validated[CONF_SHOW_TOPN] == EXPECTED_TOPN


def test_the_fake_rejects_what_home_assistant_would_reject() -> None:
    """Test that the double is strict about the keywords it is called with.

    A fake that swallows `**kwargs` would let the migration pass a keyword
    Home Assistant does not take and no test would notice, which is exactly
    what `version=` is - accepted from 2026.1 on, the version `hacs.json`
    requires, and rejected by an older core.
    """
    entries = FakeConfigEntries()
    entry = FakeConfigEntry({"feed_url": "https://example.com"})
    with pytest.raises(TypeError):
        entries.async_update_entry(entry, nonsense=1)
    assert entries.updates == []
    assert entries.async_update_entry(entry, version=CONFIG_ENTRY_VERSION) is True


def test_migration_writes_the_new_version_through_home_assistant() -> None:
    """Test that the migration hands the new version to async_update_entry.

    Bumping `entry.version` is the one thing the migration cannot do on its
    own - Home Assistant has to be told - so pin that the keyword is passed
    and that it is one Home Assistant accepts.
    """
    entry = FakeConfigEntry(
        {"feed_url": "https://example.com", CONF_SHOW_TOPN: OLD_MATERIALISED_TOPN},
    )
    hass = migrate(entry)
    assert len(hass.config_entries.updates) == 1
    assert hass.config_entries.updates[0]["version"] == CONFIG_ENTRY_VERSION


def options_schema() -> vol.Schema:
    """Return the schema the options form is built from."""
    flow = FeedparserOptionsFlowHandler()
    flow.config_entry = FakeConfigEntry({"feed_url": "https://example.com"})  # type: ignore[assignment]
    return asyncio.run(flow.async_step_init())["data_schema"]


def test_options_reject_a_negative_max_text_length() -> None:
    """Test that the UI cannot switch the truncation off behind the user's back.

    `_truncate_entry` reads every value at or below NO_TEXT_LIMIT as "keep the
    full text", so a negative number would silently disable the truncation
    the field is there to configure. The YAML schema uses cv.positive_int.
    """
    with pytest.raises(vol.Invalid):
        options_schema()({CONF_MAX_TEXT_LENGTH: -1})


def test_options_accept_the_values_the_field_is_for() -> None:
    """Test that the length the user may legitimately pick still goes through."""
    schema = options_schema()
    assert schema({CONF_MAX_TEXT_LENGTH: NO_TEXT_LIMIT})[CONF_MAX_TEXT_LENGTH] == (
        NO_TEXT_LIMIT
    )
    assert (
        schema({CONF_MAX_TEXT_LENGTH: DEFAULT_MAX_TEXT_LENGTH})[CONF_MAX_TEXT_LENGTH]
        == DEFAULT_MAX_TEXT_LENGTH
    )
