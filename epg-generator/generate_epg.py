#!/usr/bin/env python3
"""
Generates an XMLTV guide for "Premier League Goal Rush" by detecting
windows where multiple Premier League matches kick off at the same
time (the classic simultaneous "blackout slot" pattern Peacock uses
for its whip-around Goal Rush coverage).

Data source: openfootball/england (free, public domain, no API key)
https://github.com/openfootball/england
Format reference: https://github.com/openfootball/football.txt

NOTE: Peacock does not publish which weeks actually get Goal Rush
coverage ("availability varies" per their own help docs). This script
uses a heuristic — simultaneous kickoffs — as a proxy for it. Tune
MIN_CONCURRENT_MATCHES via environment variable if it's over- or
under-firing for your needs.
"""

import os
import re
import sys
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# ---- Configuration (all overridable via environment variables) ----
SEASON = os.environ.get("SEASON", "2026-27")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "PremierLeagueGoalRush.us")
CHANNEL_NAME = os.environ.get("CHANNEL_NAME", "Premier League Goal Rush")
CHANNEL_ICON = os.environ.get("CHANNEL_ICON", "")
MIN_CONCURRENT_MATCHES = int(os.environ.get("MIN_CONCURRENT_MATCHES", "3"))
PROGRAMME_DURATION_MINUTES = int(os.environ.get("PROGRAMME_DURATION_MINUTES", "135"))
PAST_DAYS_TO_KEEP = int(os.environ.get("PAST_DAYS_TO_KEEP", "1"))
OUTPUT_PATH = os.environ.get("OUTPUT_PATH", "/output/guide.xml")

# How many upcoming Goal Rush windows to generate the guide out to.
# <= 0 means unlimited (generate through the end of the season).
MATCHDAYS_AHEAD = int(os.environ.get("MATCHDAYS_AHEAD", "3"))

# Timezone used only to decide where "day" boundaries fall when
# splitting filler into daily blocks. This should generally match
# whatever timezone your EPG consumer (e.g. Dispatcharr) displays in,
# so a filler block lines up with a real calendar day on-screen rather
# than splitting at an odd local hour.
DAY_BOUNDARY_TZ = ZoneInfo(os.environ.get("DAY_BOUNDARY_TZ", "UTC"))

FILLER_ENABLED = os.environ.get("FILLER_ENABLED", "true").lower() not in ("false", "0", "no")
FILLER_TITLE = os.environ.get("FILLER_TITLE", "Premier League Goal Rush is not live right now")
FILLER_DESC = os.environ.get(
    "FILLER_DESC",
    "No simultaneous Premier League fixtures are scheduled for this time. "
    "Check back during Premier League match windows for live Goal Rush coverage.",
)
# Skip filler blocks shorter than this — avoids noisy sliver entries
# from rounding/edge cases.
MIN_FILLER_GAP_MINUTES = int(os.environ.get("MIN_FILLER_GAP_MINUTES", "2"))

# Kickoff times in the source data are UK local time
UK_TZ = ZoneInfo("Europe/London")
UTC = timezone.utc

DATA_URLS = [
    f"https://raw.githubusercontent.com/openfootball/england/master/{SEASON}/1-premierleague.txt",
    # Fallback: JSON mirror (usually only available for completed seasons)
    f"https://raw.githubusercontent.com/openfootball/football.json/master/{SEASON}/en.1.json",
]

MATCHDAY_RE = re.compile(r"^\s*[▪*]\s*(Matchday\s+\d+.*)$")
# e.g. "  Sat Aug 29" or "  Fri Aug 21 2026" or "  Sat Jan 2 2027"
DAY_RE = re.compile(
    r"^\s{1,4}(?P<wd>[A-Z][a-z]{2})\s+(?P<mon>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})(?:\s+(?P<year>\d{4}))?\s*$"
)
# e.g. "    20:00  Arsenal FC              v Coventry City FC"
# or continuation "           Nottingham Forest FC    v Leeds United FC"
MATCH_RE = re.compile(
    r"^\s+(?:(?P<time>\d{1,2}:\d{2})\s+)?(?P<team1>.+?)\s+v\s+(?P<team2>.+?)\s*$"
)

MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def fetch_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": "goalrush-epg/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def parse_football_txt(text, season):
    """Parses the openfootball football.txt format into a list of
    {date: 'YYYY-MM-DD', time: 'HH:MM', team1, team2, round} dicts."""
    season_start_year = int(season.split("-")[0])
    current_year = season_start_year
    current_date = None
    current_round = ""
    current_time = None
    matches = []

    for line in text.splitlines():
        if not line.strip():
            continue

        m = MATCHDAY_RE.match(line)
        if m:
            current_round = m.group(1).strip()
            current_time = None
            continue

        m = DAY_RE.match(line)
        if m and " v " not in line:
            mon = MONTHS.get(m.group("mon"))
            day = int(m.group("day"))
            year = int(m.group("year")) if m.group("year") else current_year
            current_year = year
            current_date = f"{year:04d}-{mon:02d}-{day:02d}"
            current_time = None
            continue

        m = MATCH_RE.match(line)
        if m and current_date:
            if m.group("time"):
                current_time = m.group("time")
                if len(current_time.split(":")[0]) == 1:
                    current_time = "0" + current_time
            if current_time is None:
                continue  # can't place this match without a kickoff time
            matches.append(
                {
                    "date": current_date,
                    "time": current_time,
                    "team1": m.group("team1").strip(),
                    "team2": m.group("team2").strip(),
                    "round": current_round,
                }
            )

    return matches


def parse_json_mirror(text):
    import json

    data = json.loads(text)
    out = []
    for m in data.get("matches", []):
        if m.get("date") and m.get("time"):
            out.append(
                {
                    "date": m["date"],
                    "time": m["time"],
                    "team1": m["team1"],
                    "team2": m["team2"],
                    "round": m.get("round", ""),
                }
            )
    return out


def fetch_fixtures():
    last_err = None
    for url in DATA_URLS:
        try:
            print(f"Fetching fixtures from {url}", file=sys.stderr)
            text = fetch_text(url)
            if url.endswith(".json"):
                matches = parse_json_mirror(text)
            else:
                matches = parse_football_txt(text, SEASON)
            if matches:
                print(f"Parsed {len(matches)} fixtures for {SEASON}", file=sys.stderr)
                return matches
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
            print(f"  failed: {e}", file=sys.stderr)
            last_err = e
            continue
    raise RuntimeError(f"Could not fetch fixture data for season {SEASON}: {last_err}")


def group_by_kickoff(matches):
    groups = defaultdict(list)
    for m in matches:
        groups[(m["date"], m["time"])].append(m)
    return groups


def kickoff_to_utc(date, time):
    local_dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M").replace(tzinfo=UK_TZ)
    return local_dt.astimezone(UTC)


def floor_to_hour(dt):
    return dt.replace(minute=0, second=0, microsecond=0)


def build_programmes(groups):
    """Builds the full sorted list of qualifying Goal Rush programmes
    (not yet limited by MATCHDAYS_AHEAD)."""
    programmes = []
    now_utc = datetime.now(UTC)
    cutoff = now_utc - timedelta(days=PAST_DAYS_TO_KEEP)

    for (date, time), matches in sorted(groups.items()):
        if len(matches) < MIN_CONCURRENT_MATCHES:
            continue

        try:
            start_utc = kickoff_to_utc(date, time)
        except ValueError:
            continue

        stop_utc = start_utc + timedelta(minutes=PROGRAMME_DURATION_MINUTES)

        if stop_utc < cutoff:
            continue  # fully in the past, skip

        round_name = matches[0].get("round", "")
        fixtures_desc = "; ".join(f"{m['team1']} vs {m['team2']}" for m in matches)
        desc = f"Simultaneous Premier League coverage ({round_name}): {fixtures_desc}"

        programmes.append(
            {
                "start": start_utc,
                "stop": stop_utc,
                "title": CHANNEL_NAME,
                "desc": desc,
                "sub_title": round_name,
                "category": "Sports",
            }
        )

    programmes.sort(key=lambda p: p["start"])

    if MATCHDAYS_AHEAD > 0:
        programmes = programmes[:MATCHDAYS_AHEAD]

    return programmes


def guide_bounds(programmes):
    """Returns (guide_start, guide_end) in UTC.

    guide_start is the top of the current hour — filler never reaches
    further back than that. guide_end is the stop time of the last
    included Goal Rush programme (i.e. bounded by MATCHDAYS_AHEAD),
    with a one-day fallback if there are no upcoming programmes at
    all so the output isn't empty."""
    guide_start = floor_to_hour(datetime.now(UTC))

    if programmes:
        guide_end = max(p["stop"] for p in programmes)
        if guide_end < guide_start:
            guide_end = guide_start + timedelta(days=1)
    else:
        guide_end = guide_start + timedelta(days=1)

    return guide_start, guide_end


def day_boundaries(guide_start, guide_end, tz):
    """Returns a sorted list of UTC instants representing local
    midnight (in `tz`) for every day boundary strictly between
    guide_start and guide_end. Computed date-by-date (not via raw
    timedelta arithmetic on aware datetimes) so DST transitions in
    `tz` are handled correctly."""
    boundaries = []
    d = guide_start.astimezone(tz).date() + timedelta(days=1)
    while True:
        midnight_local = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=tz)
        midnight_utc = midnight_local.astimezone(UTC)
        if midnight_utc >= guide_end:
            break
        boundaries.append(midnight_utc)
        d = d + timedelta(days=1)
    return boundaries


def build_filler(programmes, guide_start, guide_end):
    """Fills the gaps between (and around) real Goal Rush programmes
    with placeholder blocks, split at local day boundaries so each
    non-Goal-Rush day gets its own single filler block, and Goal Rush
    days get one filler block for whatever part of that day isn't
    covered by the real programme."""
    if not FILLER_ENABLED:
        return []

    boundaries = day_boundaries(guide_start, guide_end, DAY_BOUNDARY_TZ)
    min_gap = timedelta(minutes=MIN_FILLER_GAP_MINUTES)
    filler = []

    def add_filler(start, stop):
        if stop - start >= min_gap:
            filler.append(
                {
                    "start": start,
                    "stop": stop,
                    "title": FILLER_TITLE,
                    "desc": FILLER_DESC,
                    "sub_title": "",
                    "category": None,
                }
            )

    def fill_gap(a, b):
        split_points = [a] + [t for t in boundaries if a < t < b] + [b]
        for i in range(len(split_points) - 1):
            add_filler(split_points[i], split_points[i + 1])

    pointer = guide_start
    for p in sorted(programmes, key=lambda x: x["start"]):
        if p["start"] > pointer:
            fill_gap(pointer, p["start"])
        pointer = max(pointer, p["stop"])

    if pointer < guide_end:
        fill_gap(pointer, guide_end)

    return filler


def xmltv_time(dt):
    return dt.strftime("%Y%m%d%H%M%S +0000")


def xml_escape(text):
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def write_xmltv(programmes, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<!DOCTYPE tv SYSTEM "xmltv.dtd">')
    lines.append('<tv generator-info-name="goalrush-epg" generator-info-url="local">')
    lines.append(f'  <channel id="{xml_escape(CHANNEL_ID)}">')
    lines.append(f"    <display-name>{xml_escape(CHANNEL_NAME)}</display-name>")
    if CHANNEL_ICON:
        lines.append(f'    <icon src="{xml_escape(CHANNEL_ICON)}" />')
    lines.append("  </channel>")

    for p in programmes:
        lines.append(
            f'  <programme start="{xmltv_time(p["start"])}" '
            f'stop="{xmltv_time(p["stop"])}" channel="{xml_escape(CHANNEL_ID)}">'
        )
        lines.append(f'    <title lang="en">{xml_escape(p["title"])}</title>')
        if p["sub_title"]:
            lines.append(f'    <sub-title lang="en">{xml_escape(p["sub_title"])}</sub-title>')
        lines.append(f'    <desc lang="en">{xml_escape(p["desc"])}</desc>')
        if p.get("category"):
            lines.append(f'    <category lang="en">{xml_escape(p["category"])}</category>')
        lines.append("  </programme>")

    lines.append("</tv>")

    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    os.replace(tmp_path, path)
    print(f"Wrote {len(programmes)} programme(s) to {path}", file=sys.stderr)


def main():
    matches = fetch_fixtures()
    groups = group_by_kickoff(matches)
    programmes = build_programmes(groups)
    guide_start, guide_end = guide_bounds(programmes)
    filler = build_filler(programmes, guide_start, guide_end)
    all_programmes = sorted(programmes + filler, key=lambda p: p["start"])
    write_xmltv(all_programmes, OUTPUT_PATH)


if __name__ == "__main__":
    main()
