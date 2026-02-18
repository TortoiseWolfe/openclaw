#!/usr/bin/env python3
"""Play a rendered episode on Twitch via OBS.

Usage:
  python3 play_episode.py --episode docker-basics
  python3 play_episode.py --episode docker-basics --no-stream
  python3 play_episode.py --from-schedule

Env vars:
  OBS_MEDIA_SOURCE       - OBS media source name (default: EpisodeVideo)
  OBS_PLAYBACK_SCENE     - OBS scene to switch to (default: Episode Playback)
  OBS_RENDERS_WIN_PREFIX - Windows path prefix for renders dir
"""

import argparse
import re
import glob
import json
import os
import subprocess
import sys
import time
from datetime import datetime

import obs_client
from path_utils import RENDERS_DIR, to_windows_path

EPISODES_JSON = "/home/node/clawd-twitch/episodes.json"
SCHEDULE_FILE = "/home/node/clawd-twitch/schedule.md"

MEDIA_SOURCE = os.environ.get("OBS_MEDIA_SOURCE", "EpisodeVideo")
PLAYBACK_SCENE = os.environ.get("OBS_PLAYBACK_SCENE", "Episode Playback")
STREAM_KEY = os.environ.get("OBS_STREAM_KEY", "")


def parse_schedule() -> list[dict]:
    """Parse schedule.md into a list of episode dicts."""
    if not os.path.isfile(SCHEDULE_FILE):
        return []
    rows = []
    with open(SCHEDULE_FILE) as f:
        for line in f:
            if "|" not in line or line.strip().startswith("|--"):
                continue
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if len(cells) < 6:
                continue
            date, _time, topic, series, _type, status = cells[:6]
            # Skip header row
            if date == "Date":
                continue
            rows.append({
                "date": date,
                "topic": topic,
                "series": series,
                "status": status.lower(),
                "slug": re.sub(r"\s+", "-", re.sub(r"[^a-z0-9\s-]", "", topic.lower().replace("&", "and")).strip()),
            })
    return rows


def find_series_episodes() -> list[str]:
    """Find all episode slugs in today's scheduled series, in order."""
    rows = parse_schedule()
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"[diag] Series lookup date: {today}")

    # Find today's series
    today_series = None
    for row in rows:
        if row["date"] == today:
            today_series = row["series"]
            break

    if not today_series:
        print(f"ERROR: No episode scheduled for {today}", file=sys.stderr)
        sys.exit(1)

    # Return only today's episodes in that series (not the whole series across dates)
    episodes = [row["slug"] for row in rows if row["series"] == today_series and row["date"] == today]
    print(f"Series '{today_series}': {len(episodes)} episodes")
    for i, ep in enumerate(episodes, 1):
        print(f"  {i}. {ep}")
    return episodes


def find_episode_video(episode_name: str) -> tuple[str, int]:
    """Find the most recent render for an episode. Returns (video_path, duration_sec)."""
    slug = re.sub(r"\s+", "-", re.sub(r"[^a-z0-9\s-]", "", episode_name.lower().replace("&", "and")).strip())

    # Check topic folder first (renders/{series}/{slug}/)
    for series_dir in sorted(glob.glob(os.path.join(RENDERS_DIR, "*", slug))):
        if os.path.isdir(series_dir):
            pattern = os.path.join(series_dir, "content-*.mp4")
            matches = sorted(glob.glob(pattern))
            if matches:
                video_path = matches[-1]
                result = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", video_path],
                    capture_output=True, text=True, timeout=30,
                )
                duration_sec = int(float(result.stdout.strip())) if result.returncode == 0 and result.stdout.strip() else 0
                return video_path, duration_sec

    # Check flat episode subdirectory (legacy)
    episode_dir = os.path.join(RENDERS_DIR, slug)
    if os.path.isdir(episode_dir):
        pattern = os.path.join(episode_dir, "content-*.mp4")
        matches = sorted(glob.glob(pattern))
        if matches:
            video_path = matches[-1]
            # Get duration from ffprobe
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", video_path],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0 or not result.stdout.strip():
                print(f"WARNING: ffprobe failed for {video_path}, using duration=0", file=sys.stderr)
                duration_sec = 0
            else:
                duration_sec = int(float(result.stdout.strip()))
            return video_path, duration_sec

    # Fall back to episodes.json registry (legacy)
    if not os.path.isfile(EPISODES_JSON):
        print(f"ERROR: {EPISODES_JSON} not found", file=sys.stderr)
        sys.exit(1)

    with open(EPISODES_JSON) as f:
        data = json.load(f)

    matches = [
        ep for ep in data.get("episodes", [])
        if slug in ep.get("id", "") or slug in ep.get("templateFile", "")
    ]
    if not matches:
        print(f"ERROR: No rendered episode matching '{episode_name}'", file=sys.stderr)
        available = [ep.get("id", "?") for ep in data.get("episodes", [])]
        print(f"  Available: {', '.join(set(available))}", file=sys.stderr)
        sys.exit(1)

    # Pick most recent render
    best = max(matches, key=lambda e: e.get("renderedAt", ""))
    video_rel = best["videoFile"]
    video_path = os.path.join("/home/node/clawd-twitch", video_rel)
    return video_path, best.get("durationSec", 0)


def find_scheduled_episode() -> str:
    """Find today's first scheduled episode from schedule.md."""
    rows = parse_schedule()
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"[diag] Schedule lookup date: {today}")
    for row in rows:
        if row["date"] == today:
            print(f"[diag] Selected: {row['slug']} (series={row['series']}, status={row['status']})")
            return row["slug"]
    print(f"ERROR: No episode scheduled for {today}", file=sys.stderr)
    sys.exit(1)


def play(episode_name: str, stream: bool = True) -> None:
    """Orchestrate episode playback."""
    # 1. Find video
    video_path, duration_sec = find_episode_video(episode_name)
    win_path = to_windows_path(video_path)
    print(f"Episode: {episode_name}")
    print(f"Video: {video_path}")
    print(f"OBS path: {win_path}")
    print(f"Duration: {duration_sec // 60}:{duration_sec % 60:02d}")

    # 2. Ensure OBS is running
    print("\nLaunching OBS ...")
    if not obs_client.launch_obs():
        print("ERROR: Could not launch OBS", file=sys.stderr)
        sys.exit(1)
    print("OBS connected")

    # 3. Ensure playback scene exists, switch to it, load video
    print(f"Setting up scene: {PLAYBACK_SCENE}")
    obs_client.ensure_playback_scene(PLAYBACK_SCENE, MEDIA_SOURCE)
    obs_client.switch_scene(PLAYBACK_SCENE)

    print(f"Loading video into {MEDIA_SOURCE} ...")
    obs_client.set_media_source(MEDIA_SOURCE, win_path)
    obs_client.set_input_volume(MEDIA_SOURCE, 0.0)  # normalized at render time
    time.sleep(1)

    # 4. Start playback
    obs_client.trigger_media_action(
        MEDIA_SOURCE, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART",
    )
    print("Video playing in OBS (volume: 0 dB, pre-normalized)")

    # 5. Start streaming (if requested)
    if stream:
        if STREAM_KEY:
            print("Setting Twitch stream key ...")
            obs_client.set_stream_service("rtmp_common", {
                "service": "Twitch",
                "key": STREAM_KEY,
            })
        print("Starting Twitch stream ...")
        obs_client.start_streaming()
        print("LIVE on Twitch (verified)")
    else:
        print("(--no-stream: skipping Twitch stream)")

    # 6. Wait for video to finish
    # If ffprobe failed (duration=0), use a generous fallback
    effective_timeout = max(duration_sec, 3600) + 60
    print(f"\nWaiting for video to finish (timeout: {effective_timeout}s) ...")
    poll_interval = 10
    elapsed = 0
    consecutive_errors = 0
    max_consecutive_errors = 5

    while elapsed < effective_timeout:
        time.sleep(poll_interval)
        elapsed += poll_interval
        try:
            ms = obs_client.get_media_status(MEDIA_SOURCE)
            consecutive_errors = 0
            state = ms.get("state", "")
            if state == "OBS_MEDIA_STATE_ENDED":
                print("Video finished")
                break
            cursor_sec = (ms.get("cursor", 0) or 0) / 1000
            dur = (ms.get("duration", 0) or 0) / 1000
            display_dur = dur if dur > 0 else duration_sec
            print(f"  {int(cursor_sec // 60)}:{int(cursor_sec % 60):02d}"
                  f" / {int(display_dur) // 60}:{int(display_dur) % 60:02d}")
        except Exception as e:
            consecutive_errors += 1
            print(f"  (poll error {consecutive_errors}/{max_consecutive_errors}: {e})",
                  file=sys.stderr)
            if consecutive_errors >= max_consecutive_errors:
                print(f"  ABORT: {max_consecutive_errors} consecutive poll failures",
                      file=sys.stderr)
                break

    # 7. Stop streaming
    if stream:
        print("\nStopping stream ...")
        try:
            obs_client.stop_streaming()
            print("Stream stopped (verified)")
        except Exception as e:
            print(f"ERROR: stop_streaming failed: {e}", file=sys.stderr)

    print(f"\nDone: {episode_name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Play a rendered episode via OBS")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--episode", help="Episode name (e.g. docker-basics)")
    group.add_argument("--from-schedule", action="store_true",
                       help="Auto-pick today's scheduled episode")
    parser.add_argument("--no-stream", action="store_true",
                        help="Preview in OBS without going live on Twitch")
    parser.add_argument("--show-flow", action="store_true",
                        help="Use multi-scene show flow (Starting Soon -> Intro -> Episode -> Outro)")
    parser.add_argument("--series", action="store_true",
                        help="Play all episodes in today's series consecutively")
    args = parser.parse_args()

    if args.series and args.from_schedule:
        # Series mode: play all episodes in today's series back-to-back
        episodes = find_series_episodes()
        episode_data = []
        for slug in episodes:
            try:
                video_path, duration_sec = find_episode_video(slug)
                episode_data.append((slug, video_path, duration_sec))
            except SystemExit:
                print(f"  SKIP: {slug} (no rendered video)")

        import show_flow
        show_flow.run_series_show(episode_data, stream=not args.no_stream)
        return

    if args.from_schedule:
        episode_name = find_scheduled_episode()
    else:
        episode_name = args.episode

    if args.show_flow:
        import show_flow
        video_path, duration_sec = find_episode_video(episode_name)
        show_flow.run_show(video_path, duration_sec, stream=not args.no_stream,
                           episode_name=episode_name)
    else:
        play(episode_name, stream=not args.no_stream)


if __name__ == "__main__":
    main()
