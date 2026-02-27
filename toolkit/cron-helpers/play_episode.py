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
import glob
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/app/toolkit/obs")
sys.path.insert(0, "/app/toolkit/twitch")
sys.path.insert(0, "/app/toolkit/trading")
from trading_common import ET

import obs_client
from path_utils import RENDERS_DIR, to_windows_path
from show_flow import _fuzzy_find_episode_dir

EPISODES_JSON = "/home/node/clawd-twitch/episodes.json"
SCHEDULE_FILE = "/home/node/clawd-twitch/schedule.md"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEO_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "video")

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
    today = datetime.now(ET).strftime("%Y-%m-%d")
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

    # Fuzzy fallback: tolerate 'and'/'the' differences in slug
    for series_base in sorted(glob.glob(os.path.join(RENDERS_DIR, "*"))):
        if not os.path.isdir(series_base):
            continue
        match = _fuzzy_find_episode_dir(series_base, slug)
        if match:
            hits = sorted(glob.glob(os.path.join(match, "content-*.mp4")))
            if hits:
                video_path = hits[-1]
                result = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", video_path],
                    capture_output=True, text=True, timeout=30,
                )
                duration_sec = int(float(result.stdout.strip())) if result.returncode == 0 and result.stdout.strip() else 0
                return video_path, duration_sec
    match = _fuzzy_find_episode_dir(RENDERS_DIR, slug)
    if match:
        hits = sorted(glob.glob(os.path.join(match, "content-*.mp4")))
        if hits:
            video_path = hits[-1]
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", video_path],
                capture_output=True, text=True, timeout=30,
            )
            duration_sec = int(float(result.stdout.strip())) if result.returncode == 0 and result.stdout.strip() else 0
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


def _get_scheduled_date(slug: str) -> str | None:
    """Get the scheduled air date for an episode slug from schedule.md."""
    rows = parse_schedule()
    for row in rows:
        row_slug = re.sub(r"\s+", "-", re.sub(r"[^a-z0-9\s-]", "", row["topic"].lower().replace("&", "and")).strip())
        if row_slug == slug:
            return row["date"]  # e.g. "2026-02-23"
    return None


def _get_branding_date(slug: str) -> str | None:
    """Extract the date slug from existing branding files (intro-YYYYMMDD.mp4)."""
    for series_dir in sorted(glob.glob(os.path.join(RENDERS_DIR, "*", slug))):
        if os.path.isdir(series_dir):
            intros = sorted(glob.glob(os.path.join(series_dir, "intro-*.mp4")))
            if intros:
                # intro-20260211.mp4 → 20260211
                base = os.path.basename(intros[-1])
                date_part = base.replace("intro-", "").replace(".mp4", "")
                return date_part
    flat_dir = os.path.join(RENDERS_DIR, slug)
    if os.path.isdir(flat_dir):
        intros = sorted(glob.glob(os.path.join(flat_dir, "intro-*.mp4")))
        if intros:
            base = os.path.basename(intros[-1])
            date_part = base.replace("intro-", "").replace(".mp4", "")
            return date_part
    return None


def _rerender_branding(slug: str, scheduled_date: str) -> None:
    """Re-render branding suite (intro, card, outro) with correct date."""
    from parse_episode import parse_schedule as _parse_sched, _normalize_topic, get_next_episode, is_last_in_series

    schedule = _parse_sched()
    row = next((ep for ep in schedule if _normalize_topic(ep["topic"]) == _normalize_topic(slug.replace("-", " "))), None)
    if not row:
        # Try with 'and' expanded
        for ep in schedule:
            ep_slug = re.sub(r"\s+", "-", re.sub(r"[^a-z0-9\s-]", "", ep["topic"].lower().replace("&", "and")).strip())
            if ep_slug == slug:
                row = ep
                break
    if not row:
        print(f"  WARNING: Cannot find schedule entry for {slug}, skipping re-render", file=sys.stderr)
        return

    title = row["topic"]
    series = row.get("series", "")
    next_ep = get_next_episode(title)
    last_in = is_last_in_series(title)

    branding_cmd = [
        "python3", os.path.join(VIDEO_DIR, "render_episode_branding.py"),
        "--episode", slug,
        "--title", title,
        "--topic", title,
        "--date", scheduled_date,
        "--time", row.get("time", "2:00 PM ET"),
        "--brand", os.environ.get("EPISODE_BRAND", "scripthammer"),
    ]
    if series:
        branding_cmd += ["--series", series]
    if next_ep:
        branding_cmd += ["--next-title", next_ep.get("topic", "")]
        branding_cmd += ["--next-topic", next_ep.get("topic", "")]
        if last_in:
            branding_cmd += ["--next-date", next_ep.get("date", "")]

    print(f"  Re-rendering branding for {slug} (date: {scheduled_date}) ...")
    try:
        subprocess.run(branding_cmd, check=True, timeout=600)
        print(f"  Branding re-rendered for {slug}")
    except Exception as e:
        print(f"  WARNING: Branding re-render failed: {e}", file=sys.stderr)


def ensure_branding_current(slugs: list[str]) -> None:
    """Check all episode slugs have branding with the correct scheduled date.
    Re-renders branding if the date is stale (e.g., episode was rescheduled).
    """
    for slug in slugs:
        sched_date = _get_scheduled_date(slug)
        if not sched_date:
            continue
        expected_date_slug = sched_date.replace("-", "")  # "2026-02-23" → "20260223"
        actual_date_slug = _get_branding_date(slug)
        if actual_date_slug and actual_date_slug != expected_date_slug:
            print(f"  Stale branding for {slug}: have {actual_date_slug}, need {expected_date_slug}")
            _rerender_branding(slug, sched_date)
        elif not actual_date_slug:
            print(f"  No branding found for {slug}, rendering ...")
            _rerender_branding(slug, sched_date)


def find_scheduled_episode() -> str:
    """Find today's first scheduled episode from schedule.md."""
    rows = parse_schedule()
    today = datetime.now(ET).strftime("%Y-%m-%d")
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

    # 7. Stop streaming and close OBS
    if stream:
        print("\nStopping stream ...")
        try:
            obs_client.stop_streaming()
            print("Stream stopped (verified)")
        except Exception as e:
            print(f"ERROR: stop_streaming failed: {e}", file=sys.stderr)
        try:
            obs_client.kill_obs()
            print("OBS closed")
        except Exception as e:
            print(f"ERROR: kill_obs failed: {e}", file=sys.stderr)

    print(f"\nDone: {episode_name}")


def _update_twitch_metadata(args: argparse.Namespace) -> None:
    """Update Twitch channel title/category before streaming."""
    title = getattr(args, "twitch_title", None)
    category = getattr(args, "twitch_category", None)

    # Auto-derive title from schedule when --from-schedule and no explicit --twitch-title
    if not title and getattr(args, "from_schedule", False):
        rows = parse_schedule()
        today = datetime.now(ET).strftime("%Y-%m-%d")
        for row in rows:
            if row["date"] == today:
                title = row["topic"]
                break

    # Default category when any Twitch flag is used
    if title and not category:
        category = "Software and Game Development"

    if not title and not category:
        return

    try:
        import twitch_client
        twitch_client.update_channel(title=title, game=category)
    except Exception as e:
        print(f"WARNING: Twitch metadata update failed: {e}", file=sys.stderr)
        print("Continuing with stream anyway...", file=sys.stderr)


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
    parser.add_argument("--twitch-title",
                        help="Set Twitch stream title before playing")
    parser.add_argument("--twitch-category", default=None,
                        help="Set Twitch game category (default: Software and Game Development)")
    args = parser.parse_args()

    # Update Twitch channel metadata if requested
    _update_twitch_metadata(args)

    if args.series and args.from_schedule:
        # Series mode: play all episodes in today's series back-to-back
        episodes = find_series_episodes()

        # Re-render branding if scheduled date changed since last render
        ensure_branding_current(episodes)

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
        ensure_branding_current([episode_name])
        import show_flow
        video_path, duration_sec = find_episode_video(episode_name)
        show_flow.run_show(video_path, duration_sec, stream=not args.no_stream,
                           episode_name=episode_name)
    else:
        play(episode_name, stream=not args.no_stream)


if __name__ == "__main__":
    main()
