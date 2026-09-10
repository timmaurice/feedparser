# A better Feedparser

RSS feed custom component for [Home Assistant](https://www.home-assistant.io/) which can be used in conjunction with the custom Lovelace [rss-accordion](https://github.com/timmaurice/lovelace-rss-accordion)

[![GitHub Release][releases-shield]][releases]
[![GitHub All Releases][downloads-shield]][releases]
[![License][license-shield]](LICENSE.md)

![Project Maintenance][maintenance-shield]
[![GitHub Activity][commits-shield]][commits]

[![Discord][discord-shield]][discord]
[![Community Forum][forum-shield]][forum]

## Installation

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

1. Open HACS Settings and add this repository (https://github.com/timmaurice/feedparser)
   as a Custom Repository (use **Integration** as the category).
2. The `feedparser` page should automatically load (or find it in the HACS Store)
3. Click `Install`

Alternatively, click on the button below to add the repository:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?category=Integration&repository=feedparser&owner=timmaurice)

## Configuration

### Via UI (Recommended)

1. Go to **Settings > Devices & Services**.
2. Click **Add Integration** and search for **"A better Feedparser"**.
3. Enter the name and URL of your RSS feed.
4. Once added, you can click **Configure** on the integration entry to adjust settings like the update interval, date format, inclusions, and exclusions.

The URL is fetched while you add the feed and the response has to parse as
RSS or Atom. A reachable address that is an ordinary web page is rejected with
"does not serve an RSS or Atom feed" instead of becoming an entry whose sensor
sits at 0 forever.

The **Update interval** is set in minutes and applies per feed, so a feed that changes every few minutes and one that changes every few hours can be polled at different rates. It defaults to 60 minutes. Feeds added before this option existed keep polling at the 60 minute default until you change it.

### Via configuration.yaml (Legacy)

```yaml
sensor:
  - platform: feedparser
    name: Engineering Feed
    feed_url: "https://www.sciencedaily.com/rss/matter_energy/engineering.xml"
    date_format: "%a, %d %b %Y %H:%M:%S %Z"
    scan_interval:
      hours: 3
    inclusions:
      - title
      - link
      - description
      - image
      - audio
      - published
    exclusions:
      - language

  # Configuration of the second sensor tracking a different RSS feed
  - platform: feedparser
    name: Algemeen
    feed_url: https://www.nu.nl/rss/Algemeen
    local_time: true
    show_topn: 1
```

If you wish the integration to look for enclosures in the feed entries, add `image` to `inclusions` list. Do not use `enclosure`.

`image`, `audio` and `link` are derived from the feed entry rather than copied
out of it, and they follow the same rule as every other key: `inclusions`
restricts, so once you set it, name them there to get them; `exclusions` drops
them. The `image` of the feed itself, in the `channel` attribute, is filtered
the same way.
The integration tries to get the link to an image for the given feed item and stores it under the attribute named `image`. If it fails to find it, it assigns the Home Assistant logo to it instead.

A date the parsers cannot read is left out of the entry rather than replaced
with the current time: a substituted date made the entry look as if it had just
been published and moved on every poll. The log names the value that could not
be parsed.

Note that the original `pubDate` field is available under `published` attribute for the given feed entry. Other date-type values that can be available are `updated`, `created` and `expired`. Please refer to [the documentation of the original feedparser](https://feedparser.readthedocs.io/en/latest/date-parsing.html) library.

**Configuration variables:**

| key                          | description                                                            |
| :--------------------------- | :--------------------------------------------------------------------- |
| **platform (Required)**      | The platform name                                                      |
| **name (Required)**          | Name your feed                                                         |
| **feed_url (Required)**      | The RSS feed URL                                                       |
| **date_format (Optional)**   | strftime date format for date strings **Default** `%a, %b %d %I:%M %p` |
| **local_time (Optional)**    | Whether to convert date into local time **Default** false              |
| **show_topn (Optional)**     | How many entries to fetch from the feed. **Default** in YAML: all entries |
| **max_text_length (Optional)** | Characters kept per text field, `0` keeps the full text **Default** `250` |
| **inclusions (Optional)**    | List of fields to include from populating the list                     |
| **exclusions (Optional)**    | List of fields to exclude from populating the list                     |
| **scan_interval (Optional)** | Update interval in hours                                               |

---

Note: Will return all fields if no inclusions or exclusions are specified

In the UI, **Inclusions** and **Exclusions** are pickers: the common field names
are offered for selection and anything else can still be typed in, and the
choice is stored as a list — the same shape YAML uses. Entries configured
before this, whose options held a comma separated string, are converted on
upgrade and keep filtering exactly as they did.

### HTML in summaries

`summary`, `content` and `subtitle` keep the publisher's HTML — that is what
the [rss-accordion](https://github.com/timmaurice/lovelace-rss-accordion) card
renders, with `unsafeHTML`. The markup has been through `feedparser`'s own
sanitiser first (`SANITIZE_HTML`, on by default), which applies an allow-list:
`<script>` and `<style>` elements, event handler attributes such as `onerror`
and `javascript:` URLs are stripped before the integration ever sees the value.
This integration does not sanitise on top of that, so the allow-list is part of
the contract here and there is a test pinning it. Anything reading these
attributes should still treat them as untrusted publisher content.

### Entities, devices and diagnostics

Each feed added through the UI gets a device of its own, named after the feed
and linking to the feed URL, with the sensor as its single entity. The entity
keeps the name and the entity id it already had.

YAML feeds now have a stable unique id as well (derived from the feed URL and
the name), so they show up in the entity registry and can be renamed, hidden or
assigned to an area like any other entity. They keep their entity id.

A **Download diagnostics** button on the config entry reports the settings in
effect, whether the last poll succeeded, how many entries and which keys came
out of it, and how large the state attributes are compared with the recorder's
limit. The feed URL is reported without its query string or userinfo, and the
entry texts are not included.

### Keeping the state attributes small

The entries end up in the `entries` state attribute, and Home Assistant's
recorder drops the attributes of a state larger than 16 KiB, which leaves the
sensor with a history that has no entries in it. Two settings keep a feed under
that limit:

- `show_topn` — how many entries are exposed. Feeds added through the UI default
  to the newest **5**. YAML sensors are **not** capped: the sensor's state is the
  number of entries, so a default would change the meaning of an existing
  recorder history and of any template comparing that state. A YAML sensor keeps
  every entry until you set `show_topn` yourself.
- `max_text_length` — how many characters of long text such as `summary` or
  `content` are kept, **250** by default. Values that fit are stored unchanged;
  longer ones are cut at a tag boundary and any markup left open is closed
  again, so a truncated summary is never a half written tag. Set it to `0` to
  switch the shortening off and keep the full article text — sensible for a
  short feed with narrow `inclusions`.

If the attributes are too large anyway, the integration logs a warning naming
the size and the limit, so the reason for an empty history is visible in the log.

Feeds that were added through the UI before the `show_topn` default existed were
stored with the old value of `9999` — the form's default, not a choice anyone
made. Those are migrated to `5` on upgrade. A `show_topn` you picked yourself is
never changed.

Due to how `custom_components` are loaded, it is normal to see a `ModuleNotFoundError` error on first boot after adding this, to resolve it, restart Home-Assistant.

[commits-shield]: https://img.shields.io/github/commit-activity/y/timmaurice/feedparser.svg?style=flat-square
[commits]: https://github.com/timmaurice/feedparser/commits/master
[discord]: https://discord.gg/Qa5fW2R
[discord-shield]: https://img.shields.io/discord/330944238910963714.svg?style=flat-square
[forum-shield]: https://img.shields.io/badge/community-forum-brightgreen.svg?style=flat-square
[forum]: https://community.home-assistant.io/t/custom-component-rss-feed-parser/64637
[license-shield]: https://img.shields.io/github/license/timmaurice/feedparser.svg?style=flat-square
[maintenance-shield]: https://img.shields.io/badge/maintainer-Tim%20Bayer%20%40timmaurice-blue.svg?style=flat-square
[releases-shield]: https://img.shields.io/github/release/timmaurice/feedparser.svg?style=flat-square
[downloads-shield]: https://img.shields.io/github/downloads/timmaurice/feedparser/total.svg?style=flat-square
[releases]: https://github.com/timmaurice/feedparser/releases
