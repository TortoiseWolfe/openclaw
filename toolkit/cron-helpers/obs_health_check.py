#!/usr/bin/env python3
"""OBS health check — schedule-aware.

Only launches OBS when a stream is scheduled for today (per schedule.md).
Otherwise prints "No stream scheduled today" and exits cleanly.

Usage (inside Docker):
    python3 /app/toolkit/cron-helpers/obs_health_check.py
"""

import os
import sys
from datetime import datetime, timezone

import obs_client

SCHEDULE_FILE = "/home/node/clawd-twitch/schedule.md"


def is_stream_scheduled_today() -> str | None:
    """Check schedule.md for a stream scheduled today.

    Returns the topic name if scheduled, None otherwise.
    """
    if not os.path.isfile(SCHEDULE_FILE):
        return None

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with open(SCHEDULE_FILE) as f:
        for line in f:
            if "|" not in line or line.strip().startswith("|--"):
                continue
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if len(cells) < 6:
                continue
            date, _time, topic, _series, _type, status = cells[:6]
            if date == today and status.lower() == "scheduled":
                return topic
    return None


def main() -> None:
    topic = is_stream_scheduled_today()
    if not topic:
        print("No stream scheduled today.", flush=True)
        return

    print(f"Stream scheduled: {topic}", flush=True)

    # Check if OBS launcher is reachable
    try:
        launcher = obs_client.launcher_status()
        running = launcher.get("running", False)
    except Exception as e:
        print(f"OBS launcher not reachable: {e}", flush=True)
        print("Start obs_launcher.py on the Windows host.", flush=True)
        sys.exit(1)

    if running:
        # OBS is running — report status
        try:
            status = obs_client.get_status()
            streaming = status.get("streaming", False)
            scene = status.get("current_scene", "?")
            print(f"OBS running — scene: {scene}, streaming: {streaming}",
                  flush=True)
        except Exception:
            print("OBS process running but WebSocket not connected.",
                  flush=True)
    else:
        # OBS not running — launch it
        print("OBS not running, launching...", flush=True)
        try:
            ok = obs_client.launch_obs()
            if ok:
                print("OBS launched successfully.", flush=True)
            else:
                print("Failed to launch OBS.", flush=True)
                sys.exit(1)
        except Exception as e:
            print(f"Launch failed: {e}", flush=True)
            sys.exit(1)


if __name__ == "__main__":
    main()
