#!/usr/bin/env python3
"""
Runs generate_epg.main() immediately, then re-runs it once a day at a
fixed UTC hour. Implemented as a plain Python loop (instead of cron)
so it naturally inherits the container's environment variables without
any shell re-parsing/quoting involved.
"""

import os
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone

import generate_epg

REFRESH_HOUR_UTC = int(os.environ.get("REFRESH_HOUR_UTC", "6"))
RETRY_DELAY_SECONDS = int(os.environ.get("RETRY_DELAY_SECONDS", "1800"))  # 30 min


def next_run_time(hour):
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def run_once():
    print(f"[{datetime.now(timezone.utc).isoformat()}] Running fetch...", flush=True)
    try:
        generate_epg.main()
        return True
    except Exception:
        print("Fetch failed:", file=sys.stderr, flush=True)
        traceback.print_exc()
        return False


def main():
    while True:
        ok = run_once()
        if ok:
            target = next_run_time(REFRESH_HOUR_UTC)
            sleep_seconds = (target - datetime.now(timezone.utc)).total_seconds()
            print(
                f"Next refresh at {target.isoformat()} "
                f"(sleeping {sleep_seconds / 3600:.1f}h)",
                flush=True,
            )
        else:
            sleep_seconds = RETRY_DELAY_SECONDS
            print(f"Will retry in {sleep_seconds / 60:.0f} min", flush=True)

        time.sleep(max(sleep_seconds, 60))


if __name__ == "__main__":
    main()
