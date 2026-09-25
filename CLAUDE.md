# Project Overview

This project is a custom integration for Home Assistant that parses RSS/Atom feeds into sensors. Each configured feed becomes one sensor whose state is the number of entries and whose `entries` attribute holds the parsed items (title, link, image, audio, published date, …). A `channel` attribute carries the feed-level metadata and `feed_url` the URL it is polled from.

The integration supports both UI configuration (config flow, recommended) and legacy YAML platform configuration. Relative image and link URLs are resolved against the feed URL, and dates are normalised to UTC or local time with a configurable `strftime` format.

## Core Technologies

- **Language:** Python 3
- **Framework:** Home Assistant Integration
- **Libraries:**
  - `feedparser` for RSS/Atom parsing
  - `python-dateutil` for tolerant date parsing
  - `aiohttp` via Home Assistant's shared client session for fetching feeds

## Module Layout

| Module | Responsibility |
| --- | --- |
| `api.py` | Fetching only. `FeedparserAPI.async_fetch()` returns raw bytes, over HTTP(S) via `async_get_clientsession` or from a `file://` URL in the executor. Raises `FeedparserApiError`. |
| `parser.py` | Pure parsing. `parse_feed(content, FeedParserConfig) -> ParsedFeed`. No network, no config entries — this is what the test suite exercises directly. Also owns `state_attributes()`, the single builder for what the sensor exposes: the entity writes it, the recorder warning measures it and `diagnostics.attribute_size` reports it, so a new attribute cannot make a reported size the size of something else. |
| `coordinator.py` | `FeedparserCoordinator` (a `DataUpdateCoordinator`) ties the two together and owns the polling interval. `build_coordinator(hass, entry)` maps a config entry onto it. A set up entry carries its coordinator on `entry.runtime_data` (typed as `FeedparserConfigEntry`); nothing is kept in `hass.data`. A YAML sensor has no entry, so its entity holds its coordinator directly. |
| `sensor.py` | `FeedParserSensor`, a `CoordinatorEntity`. Holds no fetch or parse logic. Also carries the legacy YAML `PLATFORM_SCHEMA`. Its icon comes from `icons.json` through `translation_key`, not `_attr_icon`, so it is not written into every state. The key carries no name: both kinds of sensor set `_attr_name`, which wins over a translated one. |
| `config_flow.py` | UI setup, reconfigure and options. Validates that the URL is reachable through `api.py` and that the response parses as a feed. `async_step_reconfigure` is what moves a feed to a new URL: it rewrites `data[feed_url]` **and** the entry's `unique_id`, which is that URL. |
| `sanitize.py` | The HTML and URL allow-list every exposed value goes through. See below. |
| `diagnostics.py` | `async_get_config_entry_diagnostics` — settings, last poll result and attribute size for a config entry. Reports keys, never entry text; redacts the feed URL's query string and userinfo. |

`sanitize.py` sanitises everything the sensor exposes. `feedparser`'s own `SANITIZE_HTML` only covers values a feed declares as HTML, so an Atom `<summary type="text">`, an RSS `<title>` or an `<author>` used to arrive with their escaped markup unescaped and live. Every string in an entry and in `channel` therefore goes through `feedparser.sanitizer._sanitize_html` here — whatever the dialect, and whatever the process-global `SANITIZE_HTML` is set to, which is why the contract does not depend on that flag. URL valued keys (`link`, `image`, `audio`, and nested `href`/`url`) skip the HTML allow-list and are checked against `feedparser.urls.make_safe_absolute_uri` on the stripped value instead, so a `javascript:` or `data:` URL cannot become an `href` or a `src`; a top level one that is rejected drops the key. `tests/test_sanitize.py` pins all of this per dialect. Both imports are private feedparser API, which is what the exact version pin in `manifest.json` is for. The pin follows the version core pins for its own `feedreader` integration, which the official image already ships; `dependabot.yml` holds feedparser back for that reason, so move it by hand when core moves. `IMAGE_REGEX` is a regex, not an HTML parser; `remove_summary_image` runs it on the sanitised summary, `process_image` on the raw one.

Feeds are polled by the coordinator's `update_interval`; the entity does not poll itself. Parsing runs in the executor because it is CPU-bound on large feeds.

## Building and Running

This is a Home Assistant integration and is not intended to be run as a standalone application.

### Installation

The recommended installation method is via the [Home Assistant Community Store (HACS)](https://hacs.xyz/).

1.  Add this repository as a custom integration repository in HACS.
2.  Install the "A better Feedparser" integration.
3.  Restart Home Assistant.

### Configuration

Configuration is handled through the Home Assistant UI:

1.  Navigate to **Settings > Devices & Services**.
2.  Click **Add Integration** and search for "A better Feedparser".
3.  Enter the name and URL of the feed.
4.  Use **Configure** on the entry to adjust the update interval, date format, inclusions and exclusions, or **Reconfigure** to point it at a different feed URL.

The update interval is set per feed in minutes (default 60, minimum 1). Changing an option reloads the config entry so the new interval takes effect immediately.

### Format

```bash
black .
```

### Linting

```bash
ruff check custom_components/ tests/
```

Note: the repository is not currently ruff-clean; do not treat existing findings as regressions. Compare counts before and after a change instead.

### Testing

```bash
python3 -m pytest tests/
```

The suite runs fully offline against the feed fixtures in `tests/data/` via `file://` URLs.

### Local Docker Testing

A `docker-compose.yml` file is provided for running a local, isolated Home Assistant instance for development and testing.

1.  Start the test environment:
    ```bash
    docker compose up -d
    ```
2.  Access the test instance at `http://localhost:8137` (user `admin`, password `password`).
3.  The local `custom_components/feedparser` directory is mounted directly into the container, so code changes only need a restart:
    ```bash
    docker restart ha-feedparser-test
    ```

The legacy `run-hass.sh` script still starts a native (non-Docker) instance against `test_hass/` if a container is not wanted.

## Releasing

Versions are managed by `bumpver` (`[tool.bumpver]` in `pyproject.toml`, and in the `dev` extra),
which keeps `pyproject.toml`, `custom_components/feedparser/manifest.json` and
`custom_components/feedparser/sensor.py` in sync. It is not `bump-my-version`, which reads
`[tool.bumpversion]` and would find no configuration here - naming the wrong tool is how the
1.2.0 bump ended up applied to the manifest by hand and to nothing else.
`tests/test_manifest.py::test_the_version_is_the_same_in_all_three_places` fails when they drift.

```bash
bumpver update --patch   # or --minor / --major
git push --follow-tags
```

Pushing a tag triggers `.github/workflows/release.yml`, which zips `custom_components/feedparser` into `feedparser.zip` and creates a draft GitHub release. `hacs.json` declares `zip_release`, so HACS installs from that asset.

## Repository Conventions

- Codeowner is `@timmaurice`.
- CI: `pull_request.yml` (pre-commit + pytest), `hassfest.yml` (Home Assistant manifest
  validation), `hacs.yaml` (HACS validation), `codeql.yml`, `release.yml`.
- Commit messages follow Conventional Commits; reference the issue in the scope, e.g. `fix(#2): resolve 500 server error in options flow`.
- User-facing strings live in `custom_components/feedparser/strings.json` and must be mirrored into `custom_components/feedparser/translations/en.json` and `translations/de.json` (kept in full key parity).
- A change to `unique_id` or to how options are stored needs a config entry migration in `async_migrate_entry` so existing installs keep their entities and history. `CONFIG_ENTRY_VERSION` and `FeedparserConfigFlow.VERSION` move together.
