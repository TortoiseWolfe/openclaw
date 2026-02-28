#!/usr/bin/env python3
"""RPG Game Night OBS orchestrator.

Manages the OBS scene setup and stream lifecycle for Star Wars D6
(West End Games) RPG sessions on Twitch. Flow:

  1. Launch OBS, create scenes
  2. Start streaming
  3. Play Star Wars D6 opening crawl (browser source)
  4. Switch to Game scene (agent GM runs session in chat)
  5. Wait for session to end (rpg_state.py end-session)
  6. Switch to Intermission, stop streaming

Scenes created:
  - RPG - Crawl:         Browser source pointing at crawl.html
  - RPG - Game:          Main game scene (text overlays, map, player cards)
  - RPG - Intermission:  Static end-of-session screen

Env vars:
  REMOTION_BASE_URL   - URL for crawl page (default: http://localhost:3100)
  RPG_CRAWL_DURATION  - Crawl animation seconds (default: 90)
  RPG_SESSION_TIMEOUT - Max session length in seconds (default: 7200)
  OBS_STREAM_KEY      - Twitch stream key
"""

import argparse
import atexit
import functools
import json
import os
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, "/app/toolkit/cron-helpers")
sys.path.insert(0, "/app/toolkit/obs")

import obs_client

# ── Config ────────────────────────────────────────────────────────

REMOTION_URL = os.environ.get("REMOTION_BASE_URL", "http://localhost:3100")
CRAWL_DURATION = int(os.environ.get("RPG_CRAWL_DURATION", "90"))
SESSION_TIMEOUT = int(os.environ.get("RPG_SESSION_TIMEOUT", "7200"))

# State file path (same as rpg_state.py — runtime data in config dir)
_DATA_DIR = os.environ.get("RPG_DATA_DIR", "/home/node/.openclaw/rpg")
STATE_FILE = os.path.join(_DATA_DIR, "state", "game-state.json")

SCENE_CRAWL = "RPG - Crawl"
SCENE_GAME = "RPG - Game"
SCENE_INTERMISSION = "RPG - Intermission"
ALL_SCENES = [SCENE_CRAWL, SCENE_GAME, SCENE_INTERMISSION]

SOURCE_CRAWL = "CrawlBrowser"
SOURCE_NARRATION = "NarrationText"
SOURCE_PLAYERS = "PlayerStatus"


# ── Emergency stream shutdown ─────────────────────────────────────

_stream_flag = [False]

signal.signal(signal.SIGTERM, functools.partial(obs_client.emergency_stop_stream, _stream_flag))
atexit.register(obs_client.emergency_stop_stream, _stream_flag)


# ── Crawl URL builder ─────────────────────────────────────────────

def build_crawl_url(
    title: str = "STAR WARS",
    subtitle: str = "West End Games D6",
    episode: str = "",
    episode_title: str = "",
    text_paragraphs: list[str] | None = None,
    duration: int = 0,
) -> str:
    """Build the crawl.html URL with query parameters."""
    params: dict[str, str] = {}
    if title and title != "STAR WARS":
        params["title"] = title
    if subtitle:
        params["subtitle"] = subtitle
    if episode:
        params["episode"] = episode
    if episode_title:
        params["episodeTitle"] = episode_title
    if text_paragraphs:
        params["text"] = "|".join(text_paragraphs)
    if duration > 0:
        params["duration"] = str(duration)

    base = f"{REMOTION_URL}/game/crawl.html"
    if params:
        return f"{base}?{urllib.parse.urlencode(params)}"
    return base


def crawl_url_from_state() -> str:
    """Build crawl URL from game-state.json crawl field."""
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # No state — use defaults (crawl.html will also try /game/state)
        return build_crawl_url()

    crawl = state.get("crawl", {})
    return build_crawl_url(
        title=crawl.get("title", "STAR WARS"),
        subtitle=crawl.get("subtitle", "West End Games D6"),
        episode=crawl.get("episode", ""),
        episode_title=crawl.get("episodeTitle", ""),
        text_paragraphs=crawl.get("paragraphs"),
        duration=CRAWL_DURATION,
    )


def closing_crawl_url_from_state() -> str | None:
    """Build closing crawl URL from game-state.json closing_crawl field.

    Returns None if no closing crawl data exists.
    """
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

    crawl = state.get("closing_crawl")
    if not crawl or not crawl.get("paragraphs"):
        return None

    return build_crawl_url(
        title=crawl.get("title", "STAR WARS"),
        subtitle=crawl.get("subtitle", "Session Complete"),
        episode=crawl.get("episode", ""),
        episode_title=crawl.get("episodeTitle", ""),
        text_paragraphs=crawl.get("paragraphs"),
        duration=CRAWL_DURATION,
    )


# ── Scene setup ───────────────────────────────────────────────────

def setup_scenes() -> None:
    """Create all RPG scenes and sources in OBS."""
    print("Setting up RPG scenes ...")

    # Create scenes
    for scene in ALL_SCENES:
        obs_client.create_scene(scene)
        print(f"  Scene: {scene}")

    # Crawl scene: browser source
    crawl_url = crawl_url_from_state()
    print(f"  Crawl URL: {crawl_url}")
    obs_client.create_browser_source(SCENE_CRAWL, SOURCE_CRAWL, crawl_url)

    # Game scene: browser source overlay (map, tokens, player cards, narration)
    overlay_url = f"{REMOTION_URL}/game/overlay.html"
    print(f"  Overlay URL: {overlay_url}")
    obs_client.create_browser_source(SCENE_GAME, "GameOverlay", overlay_url)

    # Intermission scene: simple text
    obs_client.create_text_source(
        SCENE_INTERMISSION, "IntermissionText",
        "Thanks for watching! See you next game night!",
        font_size=48,
    )

    print("All RPG scenes ready")


# ── Session monitoring ────────────────────────────────────────────

def wait_for_session_end(
    timeout: int = SESSION_TIMEOUT,
    session_proc: subprocess.Popen | None = None,
) -> None:
    """Poll game-state.json until session status is 'ended' or timeout.

    The GM agent calls `rpg_state.py end-session` when the game is done,
    which sets session.status to 'ended'. We poll every 30s.

    If session_proc is provided, also monitor the subprocess — if it exits
    (completes or crashes), treat that as session end.
    """
    print(f"\nWaiting for session to end (timeout: {timeout // 60} min) ...")
    poll_interval = 30
    elapsed = 0

    while elapsed < timeout:
        time.sleep(poll_interval)
        elapsed += poll_interval

        # Check if session runner subprocess exited
        if session_proc is not None and session_proc.poll() is not None:
            rc = session_proc.returncode
            print(f"  Session runner exited (rc={rc}) after {elapsed // 60}m {elapsed % 60}s")
            if rc != 0:
                print(f"  WARNING: Session runner exited with error code {rc}",
                      file=sys.stderr)
            return

        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
            session = state.get("session", {})
            status = session.get("status", "")

            if status == "ended":
                print(f"  Session ended after {elapsed // 60}m {elapsed % 60}s")
                return

            # Log progress
            act = session.get("act", "?")
            scene = session.get("scene", "?")
            mode = session.get("mode", "rp")
            players = len(state.get("players", {}))
            combat = "COMBAT" if state.get("combat_active") else "explore"
            print(f"  [{elapsed // 60}m] Act {act} - {scene} | "
                  f"{players} players | {combat} ({mode})")

            # Turn timer auto-advance (combat mode)
            if state.get("combat_active"):
                try:
                    result = subprocess.run(
                        ["python3", "/app/toolkit/rpg/rpg_state.py",
                         "check-timer"],
                        capture_output=True, text=True, timeout=10,
                    )
                    timer = json.loads(result.stdout)
                    if timer.get("expired"):
                        adv = subprocess.run(
                            ["python3", "/app/toolkit/rpg/rpg_state.py",
                             "auto-advance"],
                            capture_output=True, text=True, timeout=10,
                        )
                        adv_data = json.loads(adv.stdout)
                        who = adv_data.get("timed_out", "?")
                        nxt = adv_data.get("next_character", "?")
                        print(f"  AUTO-ADVANCE: {who} timed out -> {nxt}")
                except Exception as e:
                    print(f"  (turn check error: {e})")

        except (FileNotFoundError, json.JSONDecodeError):
            print(f"  [{elapsed // 60}m] (no state file)")

        # Check stream health every 5 minutes
        if elapsed % 300 == 0:
            try:
                if not obs_client.is_streaming():
                    print("  WARNING: Stream dropped! Attempting restart...",
                          file=sys.stderr)
                    obs_client.start_streaming()
                    print("  Stream restarted")
            except Exception:
                pass

    print(f"  Session timeout ({timeout}s) — ending show")


# ── Main flow ─────────────────────────────────────────────────────

def run_game_night(
    stream: bool = True,
    with_session: bool = False,
    adventure: str = "escape-from-mos-eisley",
) -> None:
    """Full game night orchestration."""
    print("=" * 60)
    print("RPG GAME NIGHT")
    print("=" * 60)

    # 1. Launch OBS
    print("\nLaunching OBS ...")
    if not obs_client.launch_obs():
        print("ERROR: Could not launch OBS", file=sys.stderr)
        sys.exit(1)
    print("OBS connected")

    # 2. Set up scenes
    setup_scenes()

    # 3. Start streaming
    global _stream_flag
    already_live = False
    if stream:
        try:
            already_live = obs_client.is_streaming()
        except Exception:
            pass
        if already_live:
            print("\nStream already live — joining existing stream")
        else:
            stream_key = os.environ.get("OBS_STREAM_KEY", "")
            if stream_key:
                print("\nSetting Twitch stream key ...")
                obs_client.set_stream_service("rtmp_common", {
                    "service": "Twitch",
                    "key": stream_key,
                })
            print("Starting Twitch stream ...")
            try:
                obs_client.start_streaming()
                _stream_flag[0] = True
                print("LIVE on Twitch (verified)")
            except RuntimeError as e:
                print(f"ERROR: Stream failed to go live: {e}", file=sys.stderr)
                obs_client.kill_obs()
                sys.exit(1)
    else:
        print("\n(--no-stream: skipping)")

    session_proc = None
    try:
        # 4. Opening crawl
        print(f"\n>> Opening Crawl ({CRAWL_DURATION}s)")
        # Refresh the crawl URL in case state was updated after scene setup
        crawl_url = crawl_url_from_state()
        obs_client.set_browser_source_url(SOURCE_CRAWL, crawl_url)
        obs_client.refresh_browser_source(SOURCE_CRAWL)
        obs_client.switch_scene(SCENE_CRAWL)
        time.sleep(CRAWL_DURATION)

        # 5. Game scene — launch session runner if requested
        print("\n>> Game Session")
        obs_client.switch_scene(SCENE_GAME)
        if with_session:
            cmd = [
                "python3", "/app/toolkit/rpg/rpg_session_runner.py",
                "--live", "--adventure", adventure,
            ]
            print(f"  Launching session runner: {' '.join(cmd)}")
            session_proc = subprocess.Popen(cmd)
            print(f"  Session runner PID: {session_proc.pid}")

        wait_for_session_end(session_proc=session_proc)

        # 5.5. Closing crawl (if session runner wrote one)
        closing_url = closing_crawl_url_from_state()
        if closing_url:
            print(f"\n>> Closing Crawl ({CRAWL_DURATION}s)")
            obs_client.set_browser_source_url(SOURCE_CRAWL, closing_url)
            obs_client.refresh_browser_source(SOURCE_CRAWL)
            obs_client.switch_scene(SCENE_CRAWL)
            time.sleep(CRAWL_DURATION)
        else:
            print("\n>> (No closing crawl data — skipping)")

        # 6. Intermission
        print("\n>> Intermission")
        obs_client.switch_scene(SCENE_INTERMISSION)
        time.sleep(30)

    except Exception as e:
        print(f"\nERROR during game night: {e}", file=sys.stderr)
    finally:
        # 7a. Clean up session runner subprocess
        if session_proc is not None and session_proc.poll() is None:
            print("Terminating session runner ...")
            session_proc.terminate()
            try:
                session_proc.wait(timeout=10)
                print(f"  Session runner exited (rc={session_proc.returncode})")
            except subprocess.TimeoutExpired:
                print("  Session runner did not exit — killing", file=sys.stderr)
                session_proc.kill()
                session_proc.wait(timeout=5)

        # 7b. Stop streaming and close OBS
        if stream and not already_live:
            print("\nStopping stream ...")
            try:
                obs_client.stop_streaming()
                _stream_flag[0] = False
                print("Stream stopped (verified)")
            except Exception as e:
                print(f"ERROR: stop_streaming failed: {e}", file=sys.stderr)
            try:
                obs_client.kill_obs()
                print("OBS closed")
            except Exception as e:
                print(f"ERROR: kill_obs failed: {e}", file=sys.stderr)
        elif stream and already_live:
            print("\n(Stream was already live — leaving it running)")

    print("\n" + "=" * 60)
    print("GAME NIGHT COMPLETE")
    print("=" * 60)


# ── CLI ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="RPG Game Night OBS orchestrator")
    parser.add_argument(
        "--no-stream", action="store_true",
        help="Preview without going live on Twitch",
    )
    parser.add_argument(
        "--setup-only", action="store_true",
        help="Create OBS scenes and exit (no stream, no session)",
    )
    parser.add_argument(
        "--crawl-only", action="store_true",
        help="Play the opening crawl and exit",
    )
    parser.add_argument(
        "--with-session", action="store_true",
        help="Launch rpg_session_runner.py during the game phase",
    )
    parser.add_argument(
        "--adventure", default="escape-from-mos-eisley",
        help="Adventure module name (default: escape-from-mos-eisley)",
    )
    args = parser.parse_args()

    if args.setup_only:
        print("Launching OBS ...")
        if not obs_client.launch_obs():
            print("ERROR: Could not launch OBS", file=sys.stderr)
            sys.exit(1)
        setup_scenes()
        return

    if args.crawl_only:
        print("Launching OBS ...")
        if not obs_client.launch_obs():
            print("ERROR: Could not launch OBS", file=sys.stderr)
            sys.exit(1)
        setup_scenes()
        crawl_url = crawl_url_from_state()
        obs_client.set_browser_source_url(SOURCE_CRAWL, crawl_url)
        obs_client.refresh_browser_source(SOURCE_CRAWL)
        obs_client.switch_scene(SCENE_CRAWL)
        print(f"Playing crawl ({CRAWL_DURATION}s) ...")
        time.sleep(CRAWL_DURATION)
        print("Crawl complete")
        return

    run_game_night(
        stream=not args.no_stream,
        with_session=args.with_session,
        adventure=args.adventure,
    )


if __name__ == "__main__":
    main()
