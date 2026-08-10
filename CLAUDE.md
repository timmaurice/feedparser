# Project Overview

This project is a custom integration for Home Assistant that parses RSS/Atom feeds into sensors. Each configured feed becomes one sensor whose state is the number of entries and whose `entries` attribute holds the parsed items (title, link, image, audio, published date, …). A `channel` attribute carries the feed-level metadata.

The integration supports both UI configuration (config flow, recommended) and legacy YAML platform configuration. Relative image and link URLs are resolved against the feed URL, and dates are normalised to UTC or local time with a configurable `strftime` format.

## Core Technologies

- **Language:** Python 3
- **Framework:** Home Assistant Integration
- **Libraries:**
  - `feedparser` for RSS/Atom parsing
  - `python-dateutil` for tolerant date parsing
  - `requests` / `requests-file` for fetching feeds (also supports `file://` URLs, used by
    the test suite)

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
- User-facing strings live in `custom_components/feedparser/strings.json` and must be mirrored into `custom_components/feedparser/translations/en.json`.
