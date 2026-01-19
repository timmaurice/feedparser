"""Config flow for Feedparser integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_DATE_FORMAT,
    CONF_EXCLUSIONS,
    CONF_FEED_URL,
    CONF_INCLUSIONS,
    CONF_LOCAL_TIME,
    CONF_REMOVE_SUMMARY_IMG,
    CONF_SHOW_TOPN,
    DEFAULT_DATE_FORMAT,
    DEFAULT_TOPN,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_FEED_URL): cv.string,
        vol.Optional(CONF_DATE_FORMAT, default=DEFAULT_DATE_FORMAT): cv.string,
        vol.Optional(CONF_SHOW_TOPN, default=DEFAULT_TOPN): cv.positive_int,
        vol.Optional(CONF_LOCAL_TIME, default=False): cv.boolean,
        vol.Optional(CONF_REMOVE_SUMMARY_IMG, default=False): cv.boolean,
    }
)


class FeedparserConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Feedparser."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                # Basic validation: check if the URL is reachable
                # Use a timeout to avoid hanging the UI
                await self.hass.async_add_executor_job(
                    lambda: requests.get(user_input[CONF_FEED_URL], timeout=10)
                )
            except Exception:  # pylint: disable=broad-except
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(user_input[CONF_FEED_URL])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_NAME], data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> FeedparserOptionsFlowHandler:
        """Get the options flow for this handler."""
        return FeedparserOptionsFlowHandler(config_entry)


class FeedparserOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Feedparser options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options

        # Helper to get value from options or data
        def get_val(key, default):
            return options.get(key, self.config_entry.data.get(key, default))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_DATE_FORMAT,
                        default=get_val(CONF_DATE_FORMAT, DEFAULT_DATE_FORMAT),
                    ): cv.string,
                    vol.Optional(
                        CONF_SHOW_TOPN, default=get_val(CONF_SHOW_TOPN, DEFAULT_TOPN)
                    ): cv.positive_int,
                    vol.Optional(
                        CONF_LOCAL_TIME, default=get_val(CONF_LOCAL_TIME, False)
                    ): cv.boolean,
                    vol.Optional(
                        CONF_REMOVE_SUMMARY_IMG,
                        default=get_val(CONF_REMOVE_SUMMARY_IMG, False),
                    ): cv.boolean,
                    vol.Optional(
                        CONF_INCLUSIONS, default=get_val(CONF_INCLUSIONS, [])
                    ): cv.string,  # Comma separated for UI simplicity
                    vol.Optional(
                        CONF_EXCLUSIONS, default=get_val(CONF_EXCLUSIONS, [])
                    ): cv.string,  # Comma separated for UI simplicity
                }
            ),
        )
