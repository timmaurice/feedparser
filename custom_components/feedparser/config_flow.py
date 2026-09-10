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
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
    MIN_TOPN,
    NO_TEXT_LIMIT,
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
    # are migrated to DEFAULT_TOPN by async_migrate_entry.
    VERSION = 2

    async def async_step_user(
        self,
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

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return FeedparserOptionsFlowHandler()


class FeedparserOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Feedparser options."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            # The number selector hands back a float, store whole minutes.
            user_input[CONF_SCAN_INTERVAL] = int(
                user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES),
            )
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options

        # Helper to get value from options or data
        def get_val(key, default):
            val = options.get(key, self.config_entry.data.get(key, default))
            if isinstance(val, list):
                return ", ".join([str(v) for v in val])
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
                        default=bool(get_val(CONF_LOCAL_TIME, False)),
                    ): bool,
                    vol.Optional(
                        CONF_REMOVE_SUMMARY_IMG,
                        default=bool(get_val(CONF_REMOVE_SUMMARY_IMG, False)),
                    ): bool,
                    vol.Optional(
                        CONF_INCLUSIONS,
                        default=get_val(CONF_INCLUSIONS, ""),
                    ): str,  # Comma separated for UI simplicity
                    vol.Optional(
                        CONF_EXCLUSIONS,
                        default=get_val(CONF_EXCLUSIONS, ""),
                    ): str,  # Comma separated for UI simplicity
                },
            ),
        )
