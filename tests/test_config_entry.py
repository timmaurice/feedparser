"""Tests the config entry migration and the defaults new entries are given."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
import voluptuous as vol

from custom_components.feedparser import CONFIG_ENTRY_VERSION, async_migrate_entry
from custom_components.feedparser.config_flow import (
    STEP_USER_DATA_SCHEMA,
    FeedparserConfigFlow,
    FeedparserOptionsFlowHandler,
)
from custom_components.feedparser.const import (
    CONF_EXCLUSIONS,
    CONF_INCLUSIONS,
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
EXPECTED_VERSION = 4
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

    # What `hass.config_entries.async_update_entry` accepts from Home Assistant
    # 2026.1 on, which is the version `hacs.json` requires. Spelled out so a
    # call passing a keyword no Home Assistant takes fails here rather than in
    # production. It cannot catch `version=` against an older core - the fake
    # accepts it, exactly as the supported one does - so a core below 2026.1 is
    # a compatibility question for `hacs.json`, not something this suite pins.
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
    migrated = asyncio.run(async_migrate_entry(hass, entry))  # type: ignore[arg-type]
    assert migrated is True
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

    A fake that swallows `**kwargs` would let the migration pass a keyword no
    Home Assistant takes and no test would notice. `version=` is not such a
    keyword: it is accepted from 2026.1 on, which is what `hacs.json` requires,
    and the fake accepts it for the same reason - so it is pinned as accepted,
    not as rejected.
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


def test_migration_turns_comma_strings_into_field_lists() -> None:
    """Test that options written by the old text field become lists.

    The options form stored what was typed - "title, published" - while the
    entry data and YAML held a list, so the value had to be reinterpreted on
    every poll. Converting it here is what keeps an existing entry filtering
    exactly as it did.
    """
    entry = FakeConfigEntry(
        {"feed_url": "https://example.com"},
        options={
            CONF_INCLUSIONS: "title, published , image",
            CONF_EXCLUSIONS: "language",
        },
    )
    migrate(entry)
    assert entry.options[CONF_INCLUSIONS] == ["title", "published", "image"]
    assert entry.options[CONF_EXCLUSIONS] == ["language"]


def test_migration_leaves_a_field_list_alone() -> None:
    """Test that a value that is already a list survives unchanged."""
    entry = FakeConfigEntry(
        {"feed_url": "https://example.com", CONF_INCLUSIONS: ["title", "link"]},
    )
    migrate(entry)
    assert entry.data[CONF_INCLUSIONS] == ["title", "link"]


def test_migration_does_not_invent_field_lists() -> None:
    """Test that an entry that never set the fields does not gain them.

    An empty list is not the same setting as "unset": it would be stored and
    read back as "no inclusions", which happens to mean the same thing today,
    but writing keys nobody configured into an entry is how a default becomes
    impossible to change later.
    """
    entry = FakeConfigEntry({"feed_url": "https://example.com"})
    migrate(entry)
    assert CONF_INCLUSIONS not in entry.data
    assert CONF_INCLUSIONS not in entry.options


def test_migration_from_version_one_applies_every_step() -> None:
    """Test that an entry that skipped a release gets both migrations."""
    entry = FakeConfigEntry(
        {
            "feed_url": "https://example.com",
            CONF_SHOW_TOPN: OLD_MATERIALISED_TOPN,
            CONF_INCLUSIONS: "title,summary",
        },
        version=1,
    )
    migrate(entry)
    assert entry.data[CONF_SHOW_TOPN] == EXPECTED_TOPN
    assert entry.data[CONF_INCLUSIONS] == ["title", "summary"]
    assert entry.version == EXPECTED_VERSION


class OptionsFlowOnFakeEntry(FeedparserOptionsFlowHandler):
    """The options flow handler, answering `config_entry` from a fake entry.

    The handler reads `self.config_entry` off the Home Assistant base class.
    From core 2024.11 on that is a read-only property, so assigning a double to
    it raises AttributeError; older cores have no such attribute at all. A
    subclass that answers the property itself works against both, and leaves
    the handler under test untouched.
    """

    def __init__(self: OptionsFlowOnFakeEntry, entry: FakeConfigEntry) -> None:
        """Initialize."""
        super().__init__()
        self._fake_entry = entry

    @property
    def config_entry(  # type: ignore[override]
        self: OptionsFlowOnFakeEntry,
    ) -> FakeConfigEntry:
        """Return the fake entry in place of the one core would resolve."""
        return self._fake_entry


def options_flow_for(entry: FakeConfigEntry) -> FeedparserOptionsFlowHandler:
    """Return an options flow handler wired to a fake config entry."""
    return OptionsFlowOnFakeEntry(entry)


def test_the_options_flow_lets_the_core_supply_the_entry() -> None:
    """Test that the options flow neither takes nor stores a config entry.

    From Home Assistant 2026.1 - the core `hacs.json` requires - `config_entry`
    on an options flow is a read-only property that resolves the entry from
    `hass` via the flow's handler id. The older pattern, where
    `async_get_options_flow` passes the entry in and `__init__` assigns
    `self.config_entry`, raises AttributeError against that property and takes
    the options form down. Both halves of the contract are pinned here because
    the suite runs against a core old enough that the broken pattern still
    works, so nothing else would notice it coming back.
    """
    entry = FakeConfigEntry({"feed_url": "https://example.com"})
    flow = FeedparserConfigFlow.async_get_options_flow(entry)  # type: ignore[arg-type]
    assert isinstance(flow, FeedparserOptionsFlowHandler)
    assert "__init__" not in vars(FeedparserOptionsFlowHandler)
    assert "config_entry" not in vars(FeedparserOptionsFlowHandler)


def schema_of(flow: FeedparserOptionsFlowHandler) -> vol.Schema:
    """Return the schema the options form is built from."""
    data_schema = asyncio.run(flow.async_step_init())["data_schema"]
    return cast(vol.Schema, data_schema)


def options_schema() -> vol.Schema:
    """Return the schema a fresh entry's options form is built from."""
    entry = FakeConfigEntry({"feed_url": "https://example.com"})
    return schema_of(options_flow_for(entry))


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


def test_options_store_the_fields_as_a_list() -> None:
    """Test that the picker hands back a list, not the old comma string.

    A text field accepted "Title,PUBLISHED" or a typo without a word and simply
    filtered the entry down to nothing; the stored value also disagreed with
    the list `data` and YAML use.
    """
    schema = options_schema()
    validated = schema({CONF_INCLUSIONS: ["title", "published"]})
    assert validated[CONF_INCLUSIONS] == ["title", "published"]


def test_options_prefill_an_old_comma_string_as_chips() -> None:
    """Test that an entry the migration has not reached still shows its fields.

    `async_migrate_entry` converts them, but the form must not fall over on an
    entry whose options are still a string - the reload order is not something
    the options flow gets to assume.
    """
    flow = options_flow_for(
        FakeConfigEntry(
            {"feed_url": "https://example.com"},
            options={CONF_INCLUSIONS: "title, published"},
        ),
    )
    defaults = schema_of(flow)({})
    assert defaults[CONF_INCLUSIONS] == ["title", "published"]


def test_migration_lifts_a_stored_show_topn_below_one() -> None:
    """Test that a number the form would reject today stops emptying a sensor.

    A `-5` stored before the validator existed used to slice the entry list
    from the end and show almost everything; the parser now clamps it to zero,
    so the same entry shows nothing at all and the only way out was the options
    form. Zero is lifted for the same reason.
    """
    for stored in (-5, 0):
        entry = FakeConfigEntry(
            {"feed_url": "https://example.com", CONF_SHOW_TOPN: stored},
            options={CONF_SHOW_TOPN: stored},
            version=3,
        )
        migrate(entry)
        assert entry.data[CONF_SHOW_TOPN] == DEFAULT_TOPN
        assert entry.options[CONF_SHOW_TOPN] == DEFAULT_TOPN


def test_migration_keeps_a_show_topn_the_form_would_accept() -> None:
    """Test that the floor does not touch a number somebody picked."""
    entry = FakeConfigEntry(
        {"feed_url": "https://example.com", CONF_SHOW_TOPN: CHOSEN_TOPN},
        version=3,
    )
    migrate(entry)
    assert entry.data[CONF_SHOW_TOPN] == CHOSEN_TOPN
    assert entry.version == EXPECTED_VERSION
