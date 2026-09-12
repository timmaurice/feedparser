"""Config flow for Feedparser integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import FeedparserAPI, FeedparserApiError
from .const import (
    CONF_DATE_FORMAT,
    CONF_EXCLUSIONS,
    CONF_FEED_URL,
    CONF_INCLUSIONS,
    CONF_LOCAL_TIME,
    CONF_MAX_TEXT_LENGTH,
    CONF_REMOVE_SUMMARY_IMG,
    CONF_SHOW_TOPN,
    DEFAULT_DATE_FORMAT,
    DEFAULT_MAX_TEXT_LENGTH,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DEFAULT_TOPN,
    DOMAIN,
    FILTERABLE_FIELDS,
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
    MIN_TOPN,
    NO_TEXT_LIMIT,
    as_field_list,
)
from .parser import is_parsable_feed

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.data_entry_flow import FlowResult

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=MIN_SCAN_INTERVAL_MINUTES,
        max=MAX_SCAN_INTERVAL_MINUTES,
        step=1,
        mode=NumberSelectorMode.BOX,
        unit_of_measurement="min",
    ),
)

# A negative length would slip past `_truncate_entry`, which reads anything at
# or below NO_TEXT_LIMIT as "keep the full text", and silently switch the
# truncation off. The YAML schema uses cv.positive_int for the same reason.
MAX_TEXT_LENGTH_VALIDATOR = vol.All(vol.Coerce(int), vol.Range(min=NO_TEXT_LIMIT))

# `parse_feed` slices the entries with this, so a negative number would slice
# from the end of the list and leave a negative number in the sensor's state,
# and zero would produce a sensor with no entries at all. The YAML schema uses
# cv.positive_int; one entry is the smallest request that means anything.
SHOW_TOPN_VALIDATOR = vol.All(vol.Coerce(int), vol.Range(min=MIN_TOPN))

# Chips rather than a text field, so the stored value is the list the rest of
# the integration works with and a field name is picked instead of typed. The
# field stays open for a custom value because a feed may carry any key.
FIELD_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=FILTERABLE_FIELDS,
        multiple=True,
        custom_value=True,
        mode=SelectSelectorMode.DROPDOWN,
    ),
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): str,
        vol.Required(CONF_FEED_URL): str,
        vol.Optional(CONF_DATE_FORMAT, default=DEFAULT_DATE_FORMAT): str,
        vol.Optional(CONF_SHOW_TOPN, default=DEFAULT_TOPN): SHOW_TOPN_VALIDATOR,
        vol.Optional(
            CONF_SCAN_INTERVAL,
            default=DEFAULT_SCAN_INTERVAL_MINUTES,
        ): SCAN_INTERVAL_SELECTOR,
        vol.Optional(CONF_LOCAL_TIME, default=False): bool,
        vol.Optional(CONF_REMOVE_SUMMARY_IMG, default=False): bool,
    },
)


async def async_validate_feed(hass: HomeAssistant, url: str) -> str | None:
    """Return the error key for `url`, or None when it serves a feed.

    Reachability alone was accepted before, which let any web page become a
    config entry.
    """
    try:
        content = await FeedparserAPI(hass).async_fetch(url)
    except (FeedparserApiError, aiohttp.InvalidURL, ValueError):
        return "cannot_connect"
    except Exception:
        # Whatever it was, it must not reach the user as an unhandled flow
        # traceback.
        _LOGGER.exception("Unexpected error fetching feed from %s", url)
        return "unknown"

    # feedparser is CPU bound and a feed can be large, so keep it off the loop.
    if not await hass.async_add_executor_job(is_parsable_feed, content):
        _LOGGER.debug("%s was reachable but is not a feed", url)
        return "invalid_feed"
    return None


class FeedparserConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Feedparser."""

    # 2: show_topn values that were only the materialised old default (9999)
    #    are migrated to DEFAULT_TOPN.
    # 3: inclusions/exclusions stored as comma separated strings become lists.
    # Both are handled by async_migrate_entry.
    VERSION = 4

    async def async_step_user(
        self: FeedparserConfigFlow,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await async_validate_feed(self.hass, user_input[CONF_FEED_URL])
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(user_input[CONF_FEED_URL])
                self._abort_if_unique_id_configured()
                # The number selector hands back a float, store whole minutes.
                user_input[CONF_SCAN_INTERVAL] = int(
                    user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES),
                )
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self: FeedparserConfigFlow,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Point an existing entry at a different feed URL.

        The URL lives in the entry's `data`, which an options flow cannot
        write, so moving a feed used to mean deleting the entry and adding it
        again - which mints a new entity id and leaves the history, the cards
        and the automations that named the old one behind. A domain change or
        a reverse proxy in front of a self hosted feed is exactly the case
        where nothing about the feed has changed except where it is served.

        The entry is resolved and written through `hass.config_entries` rather
        than through `_get_reconfigure_entry` and `async_update_reload_and_abort`,
        which do the same two things: those helpers arrived in core 2024.11 and
        the newest stubs that install on the Python the hooks run under stop at
        2024.3, so the suite could only pin stand-ins for them. Both calls used
        here exist either side of that line.
        """
        entry = self.hass.config_entries.async_get_entry(
            self.context.get("entry_id", ""),
        )
        if entry is None:
            return self.async_abort(reason="unknown_entry")

        errors: dict[str, str] = {}
        current_url: str = entry.data[CONF_FEED_URL]
        if user_input is not None:
            url = user_input[CONF_FEED_URL]
            error = await async_validate_feed(self.hass, url)
            if error:
                errors["base"] = error
            elif self._another_entry_watches(entry, url):
                errors["base"] = "already_configured"
            else:
                # The unique id is the feed URL. Leaving it behind would let
                # the entry go on claiming a URL it no longer polls, so adding
                # the old feed again would abort as a duplicate while adding
                # the new one a second time would be allowed.
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_FEED_URL: url},
                    unique_id=url,
                )
                # `update_listener` reloads the entry, the same way a changed
                # option does, so the coordinator picks the new URL up at once.
                return self.async_abort(reason="reconfigure_successful")
            current_url = url

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {vol.Required(CONF_FEED_URL, default=current_url): str},
            ),
            errors=errors,
        )

    def _another_entry_watches(
        self: FeedparserConfigFlow,
        entry: config_entries.ConfigEntry,
        url: str,
    ) -> bool:
        """Return whether a feed is already configured by a different entry.

        Both the unique id and the stored URL are checked: an entry created
        before the unique id was set carries only the latter.
        """
        return any(
            other.entry_id != entry.entry_id
            and url in (other.unique_id, other.data.get(CONF_FEED_URL))
            for other in self._async_current_entries()
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,  # noqa: ARG004
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return FeedparserOptionsFlowHandler()


class FeedparserOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Feedparser options."""

    async def async_step_init(
        self: FeedparserOptionsFlowHandler,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            # The number selector hands back a float, store whole minutes.
            user_input[CONF_SCAN_INTERVAL] = int(
                user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES),
            )
            return self.async_create_entry(title="", data=user_input)

        # From core 2024.11 on `OptionsFlow.config_entry` is a read-only
        # property that resolves the entry this flow was opened for, which is
        # why the handler takes none and stores none. The newest stubs that
        # install on the Python the hooks run under stop at core 2024.3, where
        # the attribute does not exist yet, so mypy cannot see it - a gap in
        # the pinned stubs, not in the code. hacs.json requires 2026.1.
        entry = self.config_entry  # type: ignore[attr-defined]
        options = entry.options

        # Helper to get value from options or data. A config entry is an
        # untyped mapping, so what comes back out of it is genuinely `Any`.
        def get_val(key: str, default: Any) -> Any:  # noqa: ANN401
            val = options.get(key, entry.data.get(key, default))
            return val if val is not None else default

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_DATE_FORMAT,
                        default=get_val(CONF_DATE_FORMAT, DEFAULT_DATE_FORMAT),
                    ): str,
                    vol.Optional(
                        CONF_SHOW_TOPN,
                        default=int(get_val(CONF_SHOW_TOPN, DEFAULT_TOPN)),
                    ): SHOW_TOPN_VALIDATOR,
                    vol.Optional(
                        CONF_MAX_TEXT_LENGTH,
                        default=int(
                            get_val(CONF_MAX_TEXT_LENGTH, DEFAULT_MAX_TEXT_LENGTH),
                        ),
                    ): MAX_TEXT_LENGTH_VALIDATOR,
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=int(
                            get_val(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES),
                        ),
                    ): SCAN_INTERVAL_SELECTOR,
                    vol.Optional(
                        CONF_LOCAL_TIME,
                        default=bool(get_val(CONF_LOCAL_TIME, default=False)),
                    ): bool,
                    vol.Optional(
                        CONF_REMOVE_SUMMARY_IMG,
                        default=bool(get_val(CONF_REMOVE_SUMMARY_IMG, default=False)),
                    ): bool,
                    vol.Optional(
                        CONF_INCLUSIONS,
                        default=as_field_list(get_val(CONF_INCLUSIONS, [])),
                    ): FIELD_SELECTOR,
                    vol.Optional(
                        CONF_EXCLUSIONS,
                        default=as_field_list(get_val(CONF_EXCLUSIONS, [])),
                    ): FIELD_SELECTOR,
                },
            ),
        )
