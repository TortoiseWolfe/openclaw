#!/usr/bin/env python3
"""One-command launcher for RPG game night.

Chains OBS launch → scene setup → stream → init → crawl → live session.
Refuses to run if OBS can't be reached — no point running a game nobody sees.

Used by the cron job so the Ollama agent only needs to exec a single
script with no flags to get wrong.
"""

import atexit
import functools
import os
import signal
import subprocess
import sys
import time

sys.path.insert(0, "/app/toolkit/cron-helpers")
sys.path.insert(0, "/app/toolkit/obs")

import obs_client

ADVENTURE = "escape-from-mos-eisley"
STATE = ["python3", "/app/toolkit/rpg/rpg_state.py"]
RUNNER = ["python3", "/app/toolkit/rpg/rpg_session_runner.py"]
SHOW_FLOW = ["python3", "/app/toolkit/rpg/rpg_show_flow.py"]

CRAWL_DURATION = int(os.environ.get("RPG_CRAWL_DURATION", "90"))
SCENE_CRAWL = "RPG - Crawl"
SCENE_GAME = "RPG - Game"
SCENE_INTERMISSION = "RPG - Intermission"
SOURCE_CRAWL = "CrawlBrowser"

CRAWL_TEXT = (
    "The galaxy is in turmoil. The evil GALACTIC EMPIRE tightens its grip "
    "on the Outer Rim, sending patrols to every spaceport."
    "|On the dusty streets of MOS EISLEY, a ragtag group of unlikely heroes "
    "finds themselves caught in a web of Imperial intrigue."
    "|With bounty hunters on their trail and Stormtroopers at every corner, "
    "they must find a way off this desert world before it is too late..."
)

# ── Stream safety ────────────────────────────────────────────────

_stream_flag = [False]

signal.signal(signal.SIGTERM, functools.partial(obs_client.emergency_stop_stream, _stream_flag))
signal.signal(signal.SIGINT, functools.partial(obs_client.emergency_stop_stream, _stream_flag))
atexit.register(obs_client.emergency_stop_stream, _stream_flag)


# ── Helpers ──────────────────────────────────────────────────────

def run(cmd: list[str]) -> None:
    print(f">> {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.returncode != 0:
        print(f"ERROR (exit {result.returncode}): {result.stderr.rstrip()}")
        sys.exit(result.returncode)


# ── Main ─────────────────────────────────────────────────────────

def main():
    global _stream_flag

    # 0. Launch OBS — hard requirement
    if not obs_client.is_connected():
        print("Launching OBS via host launcher ...")
        if not obs_client.launch_obs(wait=True, max_wait=30):
            print("ERROR: Cannot reach OBS. Start obs_launcher.py on the "
                  "Windows host, then retry.", file=sys.stderr)
            sys.exit(1)
    print("OBS connected")

    # 1. Init game state
    run([*STATE, "init", "--adventure", ADVENTURE, "--auto-join-bots"])

    # 2. Set opening crawl
    run([*STATE, "set-crawl",
         "--title", "STAR WARS",
         "--episode-title", "Escape from Mos Eisley",
         "--text", CRAWL_TEXT])

    # 3. OBS: scenes → stream → opening crawl
    run([*SHOW_FLOW, "--setup-only"])

    if not obs_client.is_streaming():
        stream_key = os.environ.get("OBS_STREAM_KEY", "")
        if stream_key:
            obs_client.set_stream_service("rtmp_common", {
                "service": "Twitch",
                "key": stream_key,
            })
        try:
            obs_client.start_streaming()
            _stream_flag[0] = True
            print("LIVE on Twitch")
        except RuntimeError as e:
            print(f"ERROR: Stream failed to go live: {e}", file=sys.stderr)
            obs_client.kill_obs()
            sys.exit(1)
    else:
        _stream_flag[0] = True  # track existing stream so crash triggers emergency stop
        print("Already streaming — joining existing stream")

    print(f">> Opening Crawl ({CRAWL_DURATION}s)")
    obs_client.refresh_browser_source(SOURCE_CRAWL)
    obs_client.switch_scene(SCENE_CRAWL)
    time.sleep(CRAWL_DURATION)
    obs_client.switch_scene(SCENE_GAME)

    # 4. Live session (long-running — monitored via Popen)
    print("\n>> Starting live session ...")
    proc = subprocess.Popen([*RUNNER, "--live", "--adventure", ADVENTURE])
    check_interval = 30  # seconds between health checks
    returncode = None
    while returncode is None:
        returncode = proc.poll()
        if returncode is not None:
            break
        # Monitor stream health while session runs
        if _stream_flag[0]:
            try:
                if not obs_client.is_streaming():
                    print("WARNING: OBS stream dropped mid-session!", file=sys.stderr)
            except Exception:
                pass
        time.sleep(check_interval)

    print(f"Session runner exited (rc={returncode})")

    # 5. Post-session: intermission → stop stream
    try:
        obs_client.switch_scene(SCENE_INTERMISSION)
        time.sleep(30)
    except Exception as e:
        print(f"Post-session scene error: {e}")

    if _stream_flag[0]:
        try:
            obs_client.stop_streaming()
            _stream_flag[0] = False
            print("Stream stopped")
        except Exception as e:
            print(f"Stream stop error: {e}")
        try:
            obs_client.kill_obs()
            print("OBS closed")
        except Exception as e:
            print(f"OBS close error: {e}")

    sys.exit(returncode or 0)


if __name__ == "__main__":
    main()
