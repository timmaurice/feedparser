"""Data update coordinator for the Feedparser integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_NAME, CONF_SCAN_INTERVAL
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

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
    as_field_list,
    scan_interval_from_minutes,
)
from .parser import FeedParserConfig, ParsedFeed, parse_feed

if TYPE_CHECKING:
    from datetime import timedelta

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class FeedparserCoordinator(DataUpdateCoordinator[ParsedFeed]):
    """Fetches a feed and keeps the parsed result for its sensor."""

    def __init__(
        self: FeedparserCoordinator,
        hass: HomeAssistant,
        config: FeedParserConfig,
        update_interval: timedelta,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{config.name}",
            update_interval=update_interval,
        )
        self.config = config
        self.api = FeedparserAPI(hass)

    async def _async_update_data(self: FeedparserCoordinator) -> ParsedFeed:
        """Fetch and parse the feed."""
        _LOGGER.debug(
            "Feed %s: Polling feed data from %s",
            self.config.name,
            self.config.feed_url,
        )
        try:
            content = await self.api.async_fetch(self.config.feed_url)
        except FeedparserApiError as err:
            raise UpdateFailed(str(err)) from err

        # Parsing is pure CPU work and can be slow for large feeds, so keep it
        # off the event loop.
        return await self.hass.async_add_executor_job(
            parse_feed,
            content,
            self.config,
        )


def build_coordinator(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> FeedparserCoordinator:
    """Create the coordinator for a config entry."""
    config = entry.data
    options = entry.options

    # A config entry is an untyped mapping, so what comes back out of it is
    # genuinely `Any` - the caller narrows it.
    def get_val(key: str, default: Any) -> Any:  # noqa: ANN401
        """Return a value from the options, falling back to the entry data."""
        return options.get(key, config.get(key, default))

    parser_config = FeedParserConfig(
        feed_url=config[CONF_FEED_URL],
        name=config[CONF_NAME],
        date_format=get_val(CONF_DATE_FORMAT, DEFAULT_DATE_FORMAT),
        show_topn=get_val(CONF_SHOW_TOPN, DEFAULT_TOPN),
        remove_summary_image=get_val(CONF_REMOVE_SUMMARY_IMG, default=False),
        max_text_length=int(get_val(CONF_MAX_TEXT_LENGTH, DEFAULT_MAX_TEXT_LENGTH)),
        inclusions=as_field_list(get_val(CONF_INCLUSIONS, [])),
        exclusions=as_field_list(get_val(CONF_EXCLUSIONS, [])),
        local_time=get_val(CONF_LOCAL_TIME, default=False),
    )
    return FeedparserCoordinator(
        hass,
        parser_config,
        update_interval=scan_interval_from_minutes(
            get_val(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES),
        ),
    )
