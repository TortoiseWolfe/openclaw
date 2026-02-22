#!/usr/bin/env python3
"""One-command launcher for RPG game night.

Chains OBS launch → scene setup → stream → init → crawl → live session.
Falls back gracefully to engine-only mode if OBS is unavailable.

Used by the cron job so the Ollama agent only needs to exec a single
script with no flags to get wrong.
"""

import atexit
import os
import signal
import subprocess
import sys
import time

ADVENTURE = "escape-from-mos-eisley"
STATE = ["python3", "/app/toolkit/cron-helpers/rpg_state.py"]
RUNNER = ["python3", "/app/toolkit/cron-helpers/rpg_session_runner.py"]
SHOW_FLOW = ["python3", "/app/toolkit/cron-helpers/rpg_show_flow.py"]

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

# ── OBS integration (graceful — game runs with or without OBS) ───

_obs = None  # obs_client module, set on successful import
_stream_started = False

try:
    import obs_client as _obs
except ImportError:
    pass


def _emergency_stop(signum=None, frame=None):
    """Best-effort stream stop on crash or SIGTERM."""
    global _stream_started
    if _stream_started and _obs:
        try:
            _obs.stop_streaming(verify_timeout=5)
        except Exception:
            try:
                cl = _obs._connect()
                cl.stop_stream()
                cl.disconnect()
            except Exception:
                pass
        _stream_started = False
        print("Emergency stream stop", file=sys.stderr)
    if signum is not None:
        sys.exit(1)


def _ensure_obs() -> bool:
    """Launch OBS if available. Returns True if OBS WebSocket is ready."""
    if _obs is None:
        print("OBS client not available — engine-only mode")
        return False
    try:
        if _obs.is_connected():
            print("OBS already connected")
            return True
        print("Launching OBS via host launcher ...")
        ok = _obs.launch_obs(wait=True, max_wait=30)
        if ok:
            print("OBS connected")
        else:
            print("OBS launch timed out — engine-only mode")
        return ok
    except Exception as e:
        print(f"OBS launch error: {e} — engine-only mode")
        return False


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
    global _stream_started

    # 0. Try to launch OBS (falls back to engine-only if unavailable)
    obs_ready = _ensure_obs()

    if obs_ready:
        signal.signal(signal.SIGTERM, _emergency_stop)
        atexit.register(_emergency_stop)

    # 1. Init game state
    run([*STATE, "init", "--adventure", ADVENTURE, "--auto-join-bots"])

    # 2. Set opening crawl
    run([*STATE, "set-crawl",
         "--title", "STAR WARS",
         "--episode-title", "Escape from Mos Eisley",
         "--text", CRAWL_TEXT])

    # 3. OBS: scenes → stream → opening crawl
    if obs_ready:
        # Scene setup (reuses show_flow's proven scene creation)
        run([*SHOW_FLOW, "--setup-only"])

        # Start Twitch stream
        try:
            if not _obs.is_streaming():
                stream_key = os.environ.get("OBS_STREAM_KEY", "")
                if stream_key:
                    _obs.set_stream_service("rtmp_common", {
                        "service": "Twitch",
                        "key": stream_key,
                    })
                _obs.start_streaming()
                _stream_started = True
                print("LIVE on Twitch")
            else:
                print("Already streaming — joining existing stream")
        except Exception as e:
            print(f"Stream start failed: {e}")

        # Opening crawl
        print(f">> Opening Crawl ({CRAWL_DURATION}s)")
        try:
            _obs.refresh_browser_source(SOURCE_CRAWL)
            _obs.switch_scene(SCENE_CRAWL)
            time.sleep(CRAWL_DURATION)
            _obs.switch_scene(SCENE_GAME)
        except Exception as e:
            print(f"Crawl display error: {e}")

    # 4. Live session (long-running — blocks until session ends)
    print("\n>> Starting live session ...")
    proc = subprocess.run([*RUNNER, "--live", "--adventure", ADVENTURE])

    # 5. Post-session OBS wrap-up
    if obs_ready:
        try:
            _obs.switch_scene(SCENE_INTERMISSION)
            time.sleep(30)
        except Exception as e:
            print(f"Post-session scene error: {e}")

        if _stream_started:
            try:
                _obs.stop_streaming()
                _stream_started = False
                print("Stream stopped")
            except Exception as e:
                print(f"Stream stop error: {e}")

    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
