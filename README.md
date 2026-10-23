# Premier League Goal Rush — XMLTV Generator

Generates an XMLTV guide for Peacock's "Premier League Goal Rush" whip-around
show and serves it over HTTP for Dispatcharr (or any XMLTV-consuming app).

## How it works

Peacock doesn't publish a schedule for Goal Rush specifically — it's a
whip-around show they run during weeks when several Premier League matches
kick off at the exact same time (the traditional Saturday blackout slot,
festive fixtures, the final day of the season, etc.), and availability
"varies" according to Peacock's own help docs.

This tool works around that by pulling the full Premier League fixture list
(free, no API key, from the [openfootball](https://github.com/openfootball)
project) and generating a programme block for every window where **3 or more
matches share a kickoff time**. That's a strong proxy for Goal Rush slates,
but it isn't Peacock's actual editorial calendar — tune
`MIN_CONCURRENT_MATCHES` if it over- or under-fires for you.

The rest of the guide (from the current hour through the next few Goal Rush
windows) is filled with a placeholder programme ("Premier League Goal Rush
is not live right now") so the channel has continuous, gap-free listings
instead of holes between match windows. Filler is broken into daily blocks
aligned to local midnight: a non-Goal-Rush day gets one filler block for the
whole day, and a Goal Rush day gets filler for whatever part of that day
isn't covered by the real programme (before and/or after it).

## Quick start

```bash
docker compose up -d --build
```

This starts two containers:

- **goalrush-epg-generator** — fetches fixtures once on startup, writes
  `guide.xml`, then re-runs daily at 06:00 UTC (configurable via
  `REFRESH_HOUR_UTC`).
- **goalrush-epg-server** — a tiny nginx server exposing that file at
  `http://<host>:8098/guide.xml`.

## Add it to Dispatcharr

1. In Dispatcharr, go to **EPG sources** → add a new **XMLTV** source with URL:
   `http://<host>:8098/guide.xml` (use the Docker host's IP/hostname — if
   Dispatcharr runs in the same Compose network, you can use
   `http://goalrush-epg-server/guide.xml` instead).
2. Refresh/sync the EPG source.
3. Edit your Goal Rush channel and set its **tvg-id** to
   `PremierLeagueGoalRush.us` (or whatever you set `CHANNEL_ID` to below) so
   Dispatcharr matches it to the right guide data.

## Configuration

All of these are environment variables set in `docker-compose.yml`:

| Variable | Default | Description |
|---|---|---|
| `SEASON` | `2026-27` | Premier League season to pull fixtures for |
| `CHANNEL_ID` | `PremierLeagueGoalRush.us` | tvg-id to assign in Dispatcharr |
| `CHANNEL_NAME` | `Premier League Goal Rush` | Display name / programme title |
| `CHANNEL_ICON` | *(empty)* | Optional logo URL |
| `MIN_CONCURRENT_MATCHES` | `3` | Matches needed at the same kickoff to count as a Goal Rush window |
| `PROGRAMME_DURATION_MINUTES` | `135` | Length of each generated programme block |
| `PAST_DAYS_TO_KEEP` | `1` | How far back to keep already-aired programmes in the output |
| `REFRESH_HOUR_UTC` | `6` | Hour (UTC, 0-23) the daily refresh runs at |
| `MATCHDAYS_AHEAD` | `3` | How many upcoming Goal Rush windows to generate the guide out to. `<= 0` means unlimited (through end of season) |
| `DAY_BOUNDARY_TZ` | `UTC` | Timezone used to decide where daily filler blocks split. Set this to match the timezone Dispatcharr displays in |
| `FILLER_ENABLED` | `true` | Whether to fill gaps between Goal Rush windows with a placeholder programme |
| `FILLER_TITLE` | `Premier League Goal Rush is not live right now` | Title of the placeholder programme |
| `FILLER_DESC` | *(see script)* | Description text for the placeholder programme |
| `MIN_FILLER_GAP_MINUTES` | `2` | Skip filler blocks shorter than this (avoids noisy slivers) |

The guide always starts at the top of the current hour (not further back,
regardless of `PAST_DAYS_TO_KEEP` — that variable only controls how long an
already-*started* Goal Rush programme stays visible after it begins airing,
not how far back filler reaches).

After changing anything, run `docker compose up -d --build` again.

## Updating the schedule

The generator refreshes automatically once a day (06:00 UTC by default). To
force an immediate refresh without waiting:

```bash
docker compose restart goalrush-epg-generator
```

## Next season

When the 2027-28 fixture list is published (usually mid-June), just bump
`SEASON` in `docker-compose.yml` to `2027-28` and restart.

## Limitations

- This is a heuristic, not Peacock's actual broadcast confirmation. Some
  detected windows may not actually get Goal Rush coverage, and Peacock
  could occasionally run it for a smaller slate.
- If a match gets rescheduled after the season fixture list is generated
  (common with PL matches once TV picks are confirmed closer to the date),
  the openfootball data may lag until it's updated upstream.
