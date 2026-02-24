#!/usr/bin/env python3
"""Pre-flight setup for RPG game night (runs at 7:45 PM).

Launches OBS so it's warm by 8 PM, then sets Twitch title and category.
The 8 PM launcher (rpg_game_night.py) will find OBS already running and
skip the 30-second boot wait.
"""

import sys

sys.path.insert(0, "/app/toolkit/cron-helpers")
sys.path.insert(0, "/app/toolkit/obs")
sys.path.insert(0, "/app/toolkit/twitch")

import obs_client
import twitch_client

TITLE = "Star Wars RPG Game Night"
CATEGORY = "Tabletop RPGs"


def main() -> None:
    # 1. Ensure OBS is running
    if obs_client.is_connected():
        print("OBS already connected")
    else:
        print("Launching OBS ...")
        if obs_client.launch_obs(wait=True, max_wait=30):
            print("OBS launched and connected")
        else:
            print("WARNING: OBS did not start — 8 PM launcher will retry",
                  file=sys.stderr)

    # 2. Set Twitch title + category
    twitch_client.update_channel(title=TITLE, game=CATEGORY)


if __name__ == "__main__":
    main()
