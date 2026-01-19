"""Constants for tests."""

from pathlib import Path

TESTS_PATH = Path(__file__).parent
DATA_PATH = TESTS_PATH / "data"
TEST_HASS_PATH = Path(__file__).parents[1] / "test_hass"

TEST_FEEDS = [
    {
        "has_images": True,
        "all_entries_have_images": False,
        "has_images_in_summary": True,
        "all_entries_have_summary": False,
        "sensor_config": {
            "name": "alle_meldungen",
            "feed_url": "https://rss.sueddeutsche.de/alles/",
            "inclusions": ["image", "title", "link", "published", "summary"],
            "remove_summary_image": True,
        },
    },
    {
        "has_images": True,
        "has_unique_dates": False,
        "sensor_config": {
            "name": "stern_auto",
            "feed_url": "https://www.stern.de/feed/standard/auto/",
            "inclusions": ["image", "title", "link", "published", "summary"],
        },
    },
    {
        "has_images": True,
        "sensor_config": {
            "name": "kaarst_feed",
            "feed_url": "https://rp-online.de/nrw/staedte/kaarst/feed.rss",
            "date_format": "%a, %d %b %Y %H:%M:%S",
            "inclusions": ["title", "link", "summary", "image", "published"],
        },
    },
    {
        "has_images": True,
        "sensor_config": {
            "name": "nyt_home_page",
            "feed_url": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
            "date_format": "%a, %d %b %Y %H:%M:%S",
            "inclusions": [
                "title",
                "link",
                "description",
                "summary",
                "image",
                "published",
            ],
        },
    },
    {
        "has_images": True,
        "sensor_config": {
            "name": "wdr_aktuell",
            "feed_url": "https://www1.wdr.de/mediathek/audio/wdr-aktuell-news/wdr-aktuell-152.podcast",
            "date_format": "%a, %d %b %Y %H:%M:%S",
            "local_time": True,
            "inclusions": [
                "title",
                "link",
                "description",
                "summary",
                "image",
                "audio",
                "published",
            ],
        },
    },
    {
        "has_images": True,
        "sensor_config": {
            "name": "the_daily",
            "feed_url": "https://feeds.simplecast.com/Sl5CSM3S",
            "date_format": "%a, %d %b %Y %H:%M:%S",
            "local_time": True,
            "inclusions": [
                "title",
                "link",
                "description",
                "summary",
                "image",
                "audio",
                "published",
            ],
        },
    },
    {
        "has_images": True,
        "sensor_config": {
            "name": "zeit_verbrechen",
            "feed_url": "https://feeds.simplecast.com/dnJhzmyN",
            "date_format": "%a, %d %b %Y %H:%M:%S",
            "local_time": True,
            "inclusions": [
                "title",
                "link",
                "description",
                "summary",
                "image",
                "audio",
                "published",
            ],
        },
    },
    {
        "has_images": True,
        "sensor_config": {
            "name": "ntv",
            "feed_url": "https://www.n-tv.de/23.rss",
            "date_format": "%a, %d %b %Y %H:%M:%S",
            "local_time": True,
            "inclusions": [
                "title",
                "link",
                "description",
                "summary",
                "image",
                "published",
            ],
        },
    },
]

DEFAULT_EXCLUSIONS: list[str] = []
DEFAULT_INCLUSIONS = ["image", "title", "link", "summary", "published"]
DATE_FORMAT = "%a, %d %b %Y %H:%M:%S UTC%z"

URLS_HEADERS_REQUIRED = []

