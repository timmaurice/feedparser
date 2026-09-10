# Project Overview

This project is a custom integration for Home Assistant that parses RSS/Atom feeds into sensors. Each configured feed becomes one sensor whose state is the number of entries and whose `entries` attribute holds the parsed items (title, link, image, audio, published date, …). A `channel` attribute carries the feed-level metadata.

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
| `parser.py` | Pure parsing. `parse_feed(content, FeedParserConfig) -> ParsedFeed`. No network, no config entries — this is what the test suite exercises directly. |
| `coordinator.py` | `FeedparserCoordinator` (a `DataUpdateCoordinator`) ties the two together and owns the polling interval. `build_coordinator(hass, entry)` maps a config entry onto it. |
| `sensor.py` | `FeedParserSensor`, a `CoordinatorEntity`. Holds no fetch or parse logic. Also carries the legacy YAML `PLATFORM_SCHEMA`. |
| `config_flow.py` | UI setup and options. Validates that the URL is reachable through `api.py` and that the response parses as a feed. |
| `diagnostics.py` | `async_get_config_entry_diagnostics` — settings, last poll result and attribute size for a config entry. Reports keys, never entry text; redacts the feed URL's query string and userinfo. |

HTML in `summary`/`content`/`subtitle` is passed through as it arrives from `feedparser`, which sanitises it against its own allow-list (`SANITIZE_HTML`, on by default: no `<script>`/`<style>`, no event handler attributes, no `javascript:` URLs). The integration adds no sanitising of its own, so that allow-list is a documented contract and `tests/test_parser.py::test_html_in_a_summary_arrives_sanitised` pins it. `IMAGE_REGEX` is a regex, not an HTML parser — it is only ever applied to markup feedparser has already normalised.

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
4.  Use **Configure** on the entry to adjust the update interval, date format, inclusions and exclusions.

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

Versions are managed by `bump-my-version` (configured in `pyproject.toml`), which keeps `pyproject.toml`, `custom_components/feedparser/manifest.json` and `custom_components/feedparser/sensor.py` in sync.

```bash
bump-my-version bump patch   # or minor / major
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
