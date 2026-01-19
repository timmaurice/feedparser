"""Constants for the Feedparser integration."""

from datetime import timedelta

DOMAIN = "feedparser"

CONF_FEED_URL = "feed_url"
CONF_DATE_FORMAT = "date_format"
CONF_LOCAL_TIME = "local_time"
CONF_INCLUSIONS = "inclusions"
CONF_EXCLUSIONS = "exclusions"
CONF_SHOW_TOPN = "show_topn"
CONF_REMOVE_SUMMARY_IMG = "remove_summary_image"

DEFAULT_DATE_FORMAT = "%a, %b %d %I:%M %p"
DEFAULT_SCAN_INTERVAL = timedelta(hours=1)
DEFAULT_TOPN = 9999

IMAGE_REGEX = r"<img.+?src=\"(.+?)\".+?>"
