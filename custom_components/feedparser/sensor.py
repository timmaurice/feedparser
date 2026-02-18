"""Feedparser sensor."""

from __future__ import annotations

import email.utils
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import feedparser  # type: ignore[import]
import homeassistant.helpers.config_validation as cv
import requests
import voluptuous as vol
from dateutil import parser
from feedparser import FeedParserDict
from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.const import CONF_NAME, CONF_SCAN_INTERVAL
from homeassistant.util import dt
from requests_file import FileAdapter

from .const import (
    CONF_DATE_FORMAT,
    CONF_EXCLUSIONS,
    CONF_FEED_URL,
    CONF_INCLUSIONS,
    CONF_LOCAL_TIME,
    CONF_REMOVE_SUMMARY_IMG,
    CONF_SHOW_TOPN,
    DEFAULT_DATE_FORMAT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TOPN,
    DOMAIN,
    IMAGE_REGEX,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

__version__ = "1.0.0"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_FEED_URL): cv.string,
        vol.Required(CONF_DATE_FORMAT, default=DEFAULT_DATE_FORMAT): cv.string,
        vol.Optional(CONF_LOCAL_TIME, default=False): cv.boolean,
        vol.Optional(CONF_SHOW_TOPN, default=DEFAULT_TOPN): cv.positive_int,
        vol.Optional(CONF_REMOVE_SUMMARY_IMG, default=False): cv.boolean,
        vol.Optional(CONF_INCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_EXCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): cv.time_period,
    },
)

_LOGGER: logging.Logger = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,  # noqa: ARG001
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,  # noqa: ARG001
) -> None:
    """Set up the Feedparser sensor from YAML."""
    async_add_entities(
        [
            FeedParserSensor(
                feed=config[CONF_FEED_URL],
                name=config[CONF_NAME],
                date_format=config[CONF_DATE_FORMAT],
                show_topn=config[CONF_SHOW_TOPN],
                remove_summary_image=config[CONF_REMOVE_SUMMARY_IMG],
                inclusions=config[CONF_INCLUSIONS],
                exclusions=config[CONF_EXCLUSIONS],
                scan_interval=config[CONF_SCAN_INTERVAL],
                local_time=config[CONF_LOCAL_TIME],
            ),
        ],
        update_before_add=True,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Feedparser sensor from a config entry."""
    config = entry.data
    options = entry.options

    # Helper to get value from options or data
    def get_val(key, default):
        return options.get(key, config.get(key, default))

    # Handle inclusions and exclusions which might be comma-separated strings from UI
    def to_list(val):
        if isinstance(val, str):
            return [x.strip() for x in val.split(",") if x.strip()]
        return val

    async_add_entities(
        [
            FeedParserSensor(
                feed=config[CONF_FEED_URL],
                name=config[CONF_NAME],
                date_format=get_val(CONF_DATE_FORMAT, DEFAULT_DATE_FORMAT),
                show_topn=get_val(CONF_SHOW_TOPN, DEFAULT_TOPN),
                remove_summary_image=get_val(CONF_REMOVE_SUMMARY_IMG, False),
                inclusions=to_list(get_val(CONF_INCLUSIONS, [])),
                exclusions=to_list(get_val(CONF_EXCLUSIONS, [])),
                scan_interval=timedelta(
                    hours=1
                ),  # Default, though entries handle their own polling usually
                local_time=get_val(CONF_LOCAL_TIME, False),
                entry_id=entry.entry_id,
            ),
        ],
        update_before_add=True,
    )


class FeedParserSensor(SensorEntity):
    """Representation of a Feedparser sensor."""

    _attr_force_update = True

    def __init__(
        self: FeedParserSensor,
        feed: str,
        name: str,
        date_format: str,
        show_topn: int,
        remove_summary_image: bool,
        exclusions: list[str | None],
        inclusions: list[str | None],
        scan_interval: timedelta,
        local_time: bool,
        entry_id: str | None = None,
    ) -> None:
        """Initialize the Feedparser sensor."""
        self._feed = feed
        self._attr_name = name
        self._attr_icon = "mdi:rss"
        self._date_format = date_format
        self._show_topn: int = show_topn
        self._remove_summary_image = remove_summary_image
        self._inclusions = inclusions
        self._exclusions = exclusions
        self._scan_interval = scan_interval
        self._local_time = local_time
        self._channel: dict[str, str] = {}
        self._entries: list[dict[str, str]] = []
        self._attr_attribution = "Data retrieved using RSS feedparser"
        if entry_id:
            self._attr_unique_id = f"{entry_id}"
        _LOGGER.debug("Feed %s: FeedParserSensor initialized - %s", self.name, self)

    def __repr__(self: FeedParserSensor) -> str:
        """Return the representation."""
        return (
            f'FeedParserSensor(name="{self.name}", feed="{self._feed}", '
            f"show_topn={self._show_topn}, "
            f"remove_summary_image={self._remove_summary_image}, "
            f"inclusions={self._inclusions}, "
            f"exclusions={self._exclusions}, scan_interval={self._scan_interval}, "
            f'local_time={self._local_time}, date_format="{self._date_format}")'
        )

    def update(self: FeedParserSensor) -> None:
        """Parse the feed and update the state of the sensor."""
        _LOGGER.debug("Feed %s: Polling feed data from %s", self.name, self._feed)
        s: requests.Session = requests.Session()
        s.mount("file://", FileAdapter())
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }
        s.headers.update(headers)
        res: requests.Response = s.get(self._feed)
        res.raise_for_status()
        parsed_feed: FeedParserDict = feedparser.parse(res.content)

        self._channel.clear()
        self._entries.clear()

        if not parsed_feed.feed:
            self._attr_native_value = None
            _LOGGER.warning("Feed %s: No data received.", self.name)
            return

        self._channel.update(self._generate_channel_info(parsed_feed.feed))

        if not parsed_feed.entries:
            self._attr_native_value = 0
            _LOGGER.warning("Feed %s: No entries found.", self.name)
            return

        _LOGGER.debug("Feed %s: Feed data fetched successfully", self.name)
        # set the sensor value to the amount of entries
        self._attr_native_value = (
            self._show_topn
            if len(parsed_feed.entries) > self._show_topn
            else len(parsed_feed.entries)
        )
        _LOGGER.debug(
            "Feed %s: %s entries is going to be added to the sensor",
            self.name,
            self.native_value,
        )
        self._entries.extend(self._generate_entries(parsed_feed))
        _LOGGER.debug(
            "Feed %s: Sensor state updated - %s entries",
            self.name,
            len(self.feed_entries),
        )

    def _generate_entries(
        self: FeedParserSensor,
        parsed_feed: FeedParserDict,
    ) -> list[dict[str, str]]:
        return [
            self._generate_sensor_entry(feed_entry)
            for feed_entry in parsed_feed.entries[
                : self.native_value  # type: ignore[misc]
            ]
        ]

    def _generate_sensor_entry(
        self: FeedParserSensor,
        feed_entry: FeedParserDict,
    ) -> dict[str, str]:
        _LOGGER.debug("Feed %s: Generating sensor entry for %s", self.name, feed_entry)
        sensor_entry = {}
        for key, value in feed_entry.items():
            if (
                (self._inclusions and key not in self._inclusions)
                or ("parsed" in key)
                or (key.endswith("_detail") or key == "detail")
                or (key in self._exclusions)
            ):
                continue
            if key in ["published", "updated", "created", "expired"]:
                parsed_date: datetime = self._parse_date(value)
                sensor_entry[key] = parsed_date.strftime(self._date_format)
            elif key == "image":
                sensor_entry["image"] = value.get("href")
            elif isinstance(value, (str, int, float, bool)):
                sensor_entry[key] = value

        if (
            "image" not in self._exclusions
            and "image" not in sensor_entry
            and (image := self._process_image(feed_entry))
        ):
            sensor_entry["image"] = image
        if (
            "audio" not in self._exclusions
            and "audio" not in sensor_entry
            and (audio := self._process_audio(feed_entry))
        ):
            sensor_entry["audio"] = audio
        if (
            "link" not in self._exclusions
            and "link" not in sensor_entry
            and (processed_link := self._process_link(feed_entry))
        ):
            sensor_entry["link"] = processed_link
        if self._remove_summary_image and "summary" in sensor_entry:
            sensor_entry["summary"] = re.sub(
                IMAGE_REGEX,
                "",
                sensor_entry["summary"],
            )
        _LOGGER.debug("Feed %s: Generated sensor entry: %s", self.name, sensor_entry)
        return sensor_entry

    def _generate_channel_info(
        self: FeedParserSensor,
        feed_info: FeedParserDict,
    ) -> dict[str, str]:
        _LOGGER.debug("Feed %s: Generating channel info for %s", self.name, feed_info)
        channel_info = {}
        for key, value in feed_info.items():
            if (
                (self._inclusions and key not in self._inclusions)
                or ("parsed" in key)
                or (key.endswith("_detail") or key == "detail")
                or (key in self._exclusions)
                or (key == "image")
            ):
                continue
            if key in ["published", "updated", "created", "expired"]:
                parsed_date: datetime = self._parse_date(value)
                channel_info[key] = parsed_date.strftime(self._date_format)
            elif isinstance(value, (str, int, float, bool)):
                channel_info[key] = value

        if "image" not in self._exclusions:
            image_url = feed_info.get("image", {}).get("href") or feed_info.get(
                "image",
                {},
            ).get("url")
            if not image_url and feed_info.get("logo"):
                image_url = feed_info.logo
            if image_url:
                channel_info["image"] = image_url
        _LOGGER.debug("Feed %s: Generated channel info: %s", self.name, channel_info)
        return channel_info

    def _parse_date(self: FeedParserSensor, date: str) -> datetime:
        try:
            parsed_time: datetime = email.utils.parsedate_to_datetime(date)
        except (ValueError, TypeError):
            _LOGGER.debug(
                (
                    "Feed %s: Unable to parse RFC-822 date from '%s'. This could be "
                    "caused by an incorrect pubDate format in the RSS feed. "
                    "Trying to use dateutil."
                ),
                self.name,
                date,
            )
            try:
                parsed_time = parser.parse(date)
            except (parser.ParserError, TypeError) as e:
                _LOGGER.warning(
                    "Feed %s: Unable to parse date '%s' with dateutil: %s. "
                    "Using current time as fallback.",
                    self.name,
                    date,
                    e,
                )
                parsed_time = dt.utcnow()

        if not parsed_time.tzinfo:
            _LOGGER.debug(
                "Feed %s: No timezone info found in date '%s'. Assuming UTC.",
                self.name,
                date,
            )
            parsed_time = parsed_time.replace(tzinfo=timezone.utc)
        if not parsed_time.tzname():
            parsed_time = parsed_time.replace(
                tzinfo=timezone(parsed_time.utcoffset()),  # type: ignore[arg-type]
            )

        if self._local_time:
            parsed_time = dt.as_local(parsed_time)
        else:
            parsed_time = dt.as_utc(parsed_time)
        _LOGGER.debug("Feed %s: Parsed date: %s", self.name, parsed_time)
        return parsed_time

    def _process_image(
        self: FeedParserSensor, feed_entry: FeedParserDict
    ) -> str | None:
        """Return image from feed entry."""
        if feed_entry.get("media_content"):
            for item in feed_entry["media_content"]:
                if item.get("url") and (
                    item.get("medium") == "image"
                    or (item.get("type") or "").startswith("image/")
                ):
                    return item.get("url")
        if feed_entry.get("media_thumbnail"):
            for item in feed_entry["media_thumbnail"]:
                if item.get("url"):
                    return item.get("url")
        if feed_entry.get("enclosures"):
            for enc in feed_entry["enclosures"]:
                url = enc.get("href") or enc.get("url")
                if url and (enc.get("type") or "").startswith("image/"):
                    return url
        if "summary" in feed_entry:
            images = re.findall(
                IMAGE_REGEX,
                feed_entry["summary"],
                re.S,
            )
            if images:
                return images[0]
        _LOGGER.debug(
            "Feed %s: Image is in inclusions, but no image was found for %s",
            self.name,
            feed_entry,
        )
        return None

    def _process_audio(
        self: FeedParserSensor,
        feed_entry: FeedParserDict,
    ) -> str | None:
        """Return audio from feed entry."""
        if feed_entry.get("media_content"):
            for item in feed_entry["media_content"]:
                if item.get("url") and (item.get("type") or "").startswith("audio/"):
                    return item.get("url")
        if feed_entry.get("enclosures"):
            for enc in feed_entry["enclosures"]:
                url = enc.get("href") or enc.get("url")
                if url and (enc.get("type") or "").startswith("audio/"):
                    return url
        _LOGGER.debug(
            "Feed %s: Image or audio processed, but none found for %s",
            self.name,
            feed_entry.get("title"),
        )
        return None

    def _process_link(self: FeedParserSensor, feed_entry: FeedParserDict) -> str:
        """Return link from feed entry."""
        if "links" in feed_entry:
            if len(feed_entry["links"]) > 1:
                _LOGGER.debug(
                    "Feed %s: More than one link found for %s. Using the first link.",
                    self.name,
                    feed_entry,
                )
            return feed_entry["links"][0]["href"]
        return ""

    @property
    def channel(self: FeedParserSensor) -> dict[str, str]:
        """Return channel info."""
        if hasattr(self, "_channel"):
            return self._channel
        return {}

    @property
    def feed_entries(self: FeedParserSensor) -> list[dict[str, str]]:
        """Return feed entries."""
        if hasattr(self, "_entries"):
            return self._entries
        return []

    @property
    def local_time(self: FeedParserSensor) -> bool:
        """Return local_time."""
        return self._local_time

    @local_time.setter
    def local_time(self: FeedParserSensor, value: bool) -> None:
        """Set local_time."""
        self._local_time = value

    @property
    def extra_state_attributes(self: FeedParserSensor) -> dict[str, Any]:
        """Return entity specific state attributes."""
        return {"channel": self.channel, "entries": self.feed_entries}
