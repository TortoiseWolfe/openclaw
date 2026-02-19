#!/usr/bin/env python3
"""Render a full narrated episode from a markdown template.

Usage:
  python3 render_episode.py --episode docker-basics
  python3 render_episode.py --episode docker-basics --brand scripthammer
  python3 render_episode.py --episode-from-schedule

Outputs to /home/node/clawd-twitch/renders/<title>-<timestamp>.mp4

Requires:
  - remotion-renderer service running (renders video compositions)
  - ffmpeg (for audio/video concatenation)
  - edge-tts (for TTS narration)
"""

import argparse
import atexit
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Accumulates audio temp files for cleanup even if script aborts early
_audio_cleanup_list: list[str] = []

# Layout constants matching remotion/src/lib/theme.ts
_AVAILABLE_WIDTH = 1920 - 2 * 60  # 1800px
_MAX_CODE_COL = int(_AVAILABLE_WIDTH * 0.45)  # 810px
_CODE_PADDING = 50  # 24px×2 padding + 1px×2 border
_MAX_CODE_FONT = 22
_MONO_CHAR_RATIO = 0.6  # Liberation Mono / Courier New exact ratio


def _calc_code_column_width(code_block: str | None) -> int:
    """Calculate code sidebar pixel width from content using known font metrics."""
    if not code_block:
        return 0
    max_line_len = max(
        (len(line) for line in code_block.split('\n')[:14]),
        default=0,
    )
    char_px = _MAX_CODE_FONT * _MONO_CHAR_RATIO
    return min(int(max_line_len * char_px) + _CODE_PADDING, _MAX_CODE_COL)

def _cleanup_audio():
    for f in _audio_cleanup_list:
        try:
            if os.path.exists(f):
                os.remove(f)
        except OSError:
            pass

atexit.register(_cleanup_audio)

import remotion_client

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EPISODES_DIR = os.environ.get("EPISODES_DIR", "/home/node/clawd-twitch/episodes")
SCHEDULE_FILE = os.environ.get("SCHEDULE_FILE", "/home/node/clawd-twitch/schedule.md")
EPISODES_JSON = os.environ.get("EPISODES_JSON", "/home/node/clawd-twitch/episodes.json")
OUTPUT_DIR = os.environ.get("RENDERS_DIR", "/home/node/clawd-twitch/renders")
# Audio files go in renders/_audio so remotion-renderer can access them
AUDIO_DIR = os.environ.get("AUDIO_DIR", "/home/node/clawd-twitch/renders/_audio")


def run(cmd: list[str], label: str, timeout: int = 600) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.error(f"ERROR: {label} timed out after {timeout}s")
        sys.exit(1)
    if result.returncode != 0:
        logger.error(f"ERROR: {label} failed (exit {result.returncode})")
        if result.stderr:
            for line in result.stderr.strip().split("\n")[-10:]:
                logger.error(f"  {line}")
        sys.exit(1)
    return result


def get_audio_duration(path: str) -> float:
    """Get audio duration in seconds using ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0 or not result.stdout.strip():
        logger.error(f"ERROR: ffprobe failed for {path} (exit {result.returncode})")
        if result.stderr:
            logger.error(f"  {result.stderr.strip()[:200]}")
        sys.exit(1)
    return float(result.stdout.strip())


def render_composition(composition_id: str, props: dict, output_path: str) -> bool:
    """Render a Remotion composition via the remotion-renderer service."""
    result = remotion_client.render(composition_id, props, output_path)
    if not result.get("success"):
        logger.error(f"ERROR: Render failed: {result.get('error')}")
        return False
    return True


def _map_bullet_timings(
    section, narration_text: str, timing_path: str, duration_sec: float,
) -> list[int]:
    """Map bullet appearance frames from TTS timing data.

    Supports both SentenceBoundary (edge_tts v7+) and WordBoundary events.
    Falls back to evenly-spaced timing if no data is available.
    """
    from parse_episode import get_bullet_char_offsets

    bullet_offsets = get_bullet_char_offsets(section)
    if not bullet_offsets:
        return []

    # Try to load timing JSON
    try:
        with open(timing_path) as f:
            boundaries = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        boundaries = []

    TICKS_TO_SEC = 10_000_000
    # Bullets should appear slightly BEFORE the narration reads them (anticipation)
    BULLET_LEAD_FRAMES = -15  # Show bullet 0.5 seconds before it's spoken
    narration_frames = math.ceil(duration_sec * 30)

    if not boundaries:
        # Fallback: evenly space across 85% of narration
        n = len(bullet_offsets)
        if n > 1:
            return [max(1, round(i / (n - 1) * narration_frames * 0.85)) for i in range(n)]
        return [1]

    # Match boundary text positions to bullet character offsets.
    char_pos = 0
    bullet_idx = 0
    timings: list[int] = []

    for bd in boundaries:
        text = bd["text"]
        time_sec = bd["offset"] / TICKS_TO_SEC

        # Find this text in the narration
        idx = narration_text.find(text, char_pos)
        if idx < 0:
            # Try matching just the first few words (sentence text may differ slightly)
            first_words = " ".join(text.split()[:3])
            idx = narration_text.find(first_words, char_pos)
        if idx < 0:
            continue
        char_pos = idx + len(text)

        # Assign timing to any bullets that start at or before this position
        # Bullet appears slightly before narration reaches it
        while bullet_idx < len(bullet_offsets) and idx >= bullet_offsets[bullet_idx]:
            frame = max(1, round(time_sec * 30) + BULLET_LEAD_FRAMES)
            timings.append(frame)
            bullet_idx += 1

    # Fill any unmatched bullets with evenly-spaced tail
    while len(timings) < len(bullet_offsets):
        last = timings[-1] if timings else 1
        gap = (narration_frames - last) // (len(bullet_offsets) - len(timings) + 1)
        timings.append(last + gap)

    return timings


def resolve_episode_path(name_or_path: str) -> str:
    """Resolve episode name to file path."""
    if os.path.isfile(name_or_path):
        return name_or_path
    # Try as name in episodes dir
    path = os.path.join(EPISODES_DIR, f"{name_or_path}.md")
    if os.path.isfile(path):
        return path
    logger.error(f"ERROR: Episode not found: {name_or_path}")
    logger.error(f"  Checked: {name_or_path}, {path}")
    sys.exit(1)


def find_next_scheduled_episode() -> str:
    """Read schedule.md and find the next unrendered episode."""
    if not os.path.isfile(SCHEDULE_FILE):
        logger.error("ERROR: schedule.md not found")
        sys.exit(1)

    # Load existing rendered episodes
    rendered = set()
    if os.path.isfile(EPISODES_JSON):
        with open(EPISODES_JSON) as f:
            data = json.load(f)
        for ep in data.get("episodes", []):
            rendered.add(ep.get("templateFile", ""))

    with open(SCHEDULE_FILE) as f:
        content = f.read()

    # Parse markdown table rows
    for line in content.split("\n"):
        if "|" not in line or line.strip().startswith("|--"):
            continue
        cells = [c.strip() for c in line.split("|")]
        cells = [c for c in cells if c]
        if len(cells) < 6:
            continue
        date, _time, topic, _series, _type, status = cells[:6]
        if status.lower() != "scheduled":
            continue

        # Map topic to episode file
        slug = re.sub(r"[^a-z0-9\s-]", "", topic.lower().replace("&", "and"))
        slug = re.sub(r"\s+", "-", slug.strip())
        for candidate in [slug, slug.replace("-for-", "-")]:
            ep_path = os.path.join(EPISODES_DIR, f"{candidate}.md")
            template_rel = f"episodes/{candidate}.md"
            if os.path.isfile(ep_path) and template_rel not in rendered:
                return ep_path

    logger.error("ERROR: No scheduled unrendered episodes found")
    sys.exit(1)


def register_episode(title: str, template_path: str, video_path: str,
                     brand: str, duration_sec: int, section_count: int) -> None:
    """Add rendered episode to episodes.json."""
    data = {"version": 1, "description": "Video episode registry for OBS rerun mode.",
            "episodes": [], "playlists": {}}
    if os.path.isfile(EPISODES_JSON):
        with open(EPISODES_JSON) as f:
            data = json.load(f)

    template_rel = os.path.relpath(template_path, "/home/node/clawd-twitch")
    video_rel = os.path.relpath(video_path, "/home/node/clawd-twitch")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    slug = re.sub(r"\s+", "-", re.sub(r"[^a-z0-9\s-]", "", title.lower().replace("&", "and")).strip())

    entry = {
        "id": f"{slug}-{timestamp}",
        "templateFile": template_rel,
        "videoFile": video_rel,
        "brand": brand,
        "durationSec": duration_sec,
        "sections": section_count,
        "renderedAt": datetime.now(timezone.utc).isoformat(),
    }
    data["episodes"].append(entry)

    # Atomic write: temp file + rename prevents corruption from concurrent writes
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(EPISODES_JSON), suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, EPISODES_JSON)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def main():
    parser = argparse.ArgumentParser(description="Render a full narrated episode")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--episode", help="Episode name or path")
    group.add_argument("--episode-from-schedule", action="store_true",
                       help="Auto-pick next scheduled episode")
    parser.add_argument("--brand", default="scripthammer", help="Brand theme")
    parser.add_argument("--voice", default="en-US-GuyNeural", help="Edge TTS voice")
    parser.add_argument("--no-intro", action="store_true", help="Skip narrated StreamIntro")
    parser.add_argument("--output-dir", default=OUTPUT_DIR, help="Output directory")
    args = parser.parse_args()

    # Check remotion-renderer is available
    if not remotion_client.health():
        logger.error("ERROR: remotion-renderer service not available")
        logger.error("  Start it with: docker compose up -d remotion-renderer")
        sys.exit(1)

    # Import parse_episode from same directory
    sys.path.insert(0, SCRIPT_DIR)
    from parse_episode import Episode, bullets_to_narration, parse_bullet_parts, get_bullet_char_offsets, parse_episode, get_next_episode, is_last_in_series

    # Resolve episode
    if args.episode_from_schedule:
        ep_path = find_next_scheduled_episode()
    else:
        ep_path = resolve_episode_path(args.episode)

    with open(ep_path) as f:
        episode = parse_episode(f.read())

    logger.info(f"Episode: {episode.title} ({len(episode.sections)} sections, ~{episode.duration_min} min)")

    # Check disk space (need ~1GB for renders + temp files)
    free_bytes = shutil.disk_usage(args.output_dir).free
    if free_bytes < 1024 * 1024 * 1024:
        free_mb = free_bytes // (1024 * 1024)
        logger.error(f"ABORT: Only {free_mb} MB free in {args.output_dir} — need at least 1 GB.")
        sys.exit(1)

    # Look up next episode and series info for outro
    next_ep = get_next_episode(episode.title)
    last_in_series = is_last_in_series(episode.title)
    if not next_ep and not last_in_series:
        logger.warning("WARNING: No next episode scheduled — outro will use generic CTA.")

    # Determine series from schedule
    from parse_episode import parse_schedule
    schedule = parse_schedule()
    current_sched = next((ep for ep in schedule if ep["topic"].lower() == episode.title.lower()), None)
    series = current_sched["series"] if current_sched and current_sched.get("series") else ""

    # Create audio directory for TTS files (accessible to remotion-renderer)
    os.makedirs(AUDIO_DIR, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    # Use the scheduled air date for filenames/branding, not the render date
    date_slug = current_sched["date"].replace("-", "") if current_sched else datetime.now(timezone.utc).strftime("%Y%m%d")
    slug = re.sub(r"\s+", "-", re.sub(r"[^a-z0-9\s-]", "", episode.title.lower().replace("&", "and")).strip())

    # Create episode subdirectory under series folder
    if series:
        episode_dir = os.path.join(args.output_dir, series, slug)
    else:
        episode_dir = os.path.join(args.output_dir, slug)
    os.makedirs(episode_dir, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        segment_files: list[str] = []
        audio_files_to_cleanup: list[str] = []

        # Step 1: Render narrated intro
        if not args.no_intro:
            logger.info(f"\n[intro] Rendering narrated StreamIntro ...")
            brand_names = {"turtlewolfe": "TurtleWolfe", "scripthammer": "ScriptHammer"}
            brand_display = brand_names.get(args.brand, args.brand)
            intro_narration = (
                f"Welcome to {episode.title} on {brand_display}! "
                f"In this episode, we'll cover {len(episode.sections)} sections "
                f"over about {episode.duration_min} minutes. Let's get started."
            )

            # Generate intro audio
            intro_audio_path = os.path.join(AUDIO_DIR, f"intro_{timestamp}.mp3")
            intro_timing_path = os.path.join(tmpdir, "intro_timing.json")
            run([
                "python3", os.path.join(SCRIPT_DIR, "generate_narration.py"),
                "--text", intro_narration,
                "--output", intro_audio_path,
                "--voice", args.voice,
                "--timing-output", intro_timing_path,
            ], "TTS intro")
            audio_files_to_cleanup.append(intro_audio_path)
            _audio_cleanup_list.append(intro_audio_path)

            # Get intro audio duration
            intro_duration_sec = get_audio_duration(intro_audio_path)
            intro_duration_frames = math.ceil(intro_duration_sec * 30) + 60

            # Render intro video via remotion-renderer (no audio)
            intro_props = {
                "brand": args.brand,
                "episodeTitle": episode.title,
                "audioFileName": None,  # No audio in video render
                "durationInFrames": intro_duration_frames,
            }
            intro_video_path = os.path.join(tmpdir, "intro_video.mp4")
            intro_path = os.path.join(tmpdir, "intro.mp4")
            intro_output = f"_tmp/intro_{timestamp}.mp4"
            os.makedirs(os.path.join(args.output_dir, "_tmp"), exist_ok=True)

            if render_composition("StreamIntro", intro_props, f"/renders/{intro_output}"):
                rendered_path = os.path.join(args.output_dir, intro_output)
                shutil.move(rendered_path, intro_video_path)
                logger.info(f"  Video: {os.path.getsize(intro_video_path) // 1024} KB")

                # Merge video with audio using FFmpeg
                logger.info(f"  Merging audio ...")
                run([
                    "ffmpeg", "-y",
                    "-i", intro_video_path,
                    "-i", intro_audio_path,
                    "-c:v", "copy",
                    "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "128k",
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-shortest",
                    intro_path,
                ], "Merge audio intro", timeout=120)

                segment_files.append(intro_path)
                logger.info(f"  OK: intro ({os.path.getsize(intro_path) // 1024} KB)")
            else:
                logger.warning("  WARNING: Intro render failed, skipping")

        # Step 2: Render each section
        total_sections = len(episode.sections)
        for section in episode.sections:
            logger.info(f"\n[{section.number}/{total_sections}] {section.title} ({section.time_min} min) ...")

            # Generate narration with word-boundary timing
            narration_text = bullets_to_narration(section)
            audio_filename = f"section_{section.number}_{timestamp}.mp3"
            audio_path = os.path.join(AUDIO_DIR, audio_filename)
            timing_path = os.path.join(tmpdir, f"timing_{section.number}.json")
            logger.info(f"  TTS: {len(narration_text)} chars ...")
            run([
                "python3", os.path.join(SCRIPT_DIR, "generate_narration.py"),
                "--text", narration_text,
                "--output", audio_path,
                "--voice", args.voice,
                "--timing-output", timing_path,
            ], f"TTS section {section.number}")
            audio_files_to_cleanup.append(audio_path)
            _audio_cleanup_list.append(audio_path)

            # Get audio duration
            duration_sec = get_audio_duration(audio_path)
            duration_frames = math.ceil(duration_sec * 30) + 60  # 30 fade-in + 30 fade-out
            logger.info(f"  Audio: {duration_sec:.1f}s → {duration_frames} frames")

            # Map bullet timings from word boundaries
            bullet_timings = _map_bullet_timings(
                section, narration_text, timing_path, duration_sec,
            )
            logger.debug(f"  Bullet timings: {bullet_timings[:4]}{'...' if len(bullet_timings) > 4 else ''}")

            # Build props - render video WITHOUT audio (we'll merge later with FFmpeg)
            props = {
                "brand": args.brand,
                "sectionTitle": section.title,
                "sectionNumber": section.number,
                "totalSections": total_sections,
                "bullets": [parse_bullet_parts(b) for b in section.bullets],
                "codeBlock": section.code_block,
                "codeLanguage": section.code_language,
                "codeColumnWidth": _calc_code_column_width(section.code_block),
                "audioFileName": None,  # No audio in video render
                "durationInFrames": duration_frames,
                "bulletTimings": bullet_timings,
            }

            # Render video segment via remotion-renderer (no audio)
            segment_output = f"_tmp/segment_{section.number}_{timestamp}.mp4"
            video_only_path = os.path.join(tmpdir, f"video_{section.number}.mp4")
            segment_path = os.path.join(tmpdir, f"segment_{section.number}.mp4")
            logger.info(f"  Rendering NarratedSegment (video only) ...")

            if render_composition("NarratedSegment", props, f"/renders/{segment_output}"):
                rendered_path = os.path.join(args.output_dir, segment_output)
                shutil.move(rendered_path, video_only_path)
                logger.info(f"  Video: {os.path.getsize(video_only_path) // 1024} KB")
            else:
                logger.error(f"  ERROR: Segment {section.number} render failed")
                sys.exit(1)

            # Merge video with audio using FFmpeg
            logger.info(f"  Merging audio ...")
            run([
                "ffmpeg", "-y",
                "-i", video_only_path,
                "-i", audio_path,
                "-c:v", "copy",  # Keep video codec
                "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "128k",
                "-map", "0:v:0", "-map", "1:a:0",
                "-shortest",
                segment_path,
            ], f"Merge audio section {section.number}", timeout=120)

            segment_files.append(segment_path)
            size_kb = os.path.getsize(segment_path) // 1024
            logger.info(f"  OK: segment_{section.number}.mp4 ({size_kb} KB)")

        # Cleanup audio files
        for audio_file in audio_files_to_cleanup:
            if os.path.exists(audio_file):
                os.remove(audio_file)

        # Cleanup temp render directory
        tmp_render_dir = os.path.join(args.output_dir, "_tmp")
        if os.path.exists(tmp_render_dir):
            shutil.rmtree(tmp_render_dir)

        # Step 3: FFmpeg concat using filter (more reliable than demuxer)
        n = len(segment_files)
        logger.info(f"\n[concat] Joining {n} segments ...")

        final_filename = f"content-{date_slug}.mp4"
        final_path = os.path.join(episode_dir, final_filename)

        # Build filter_complex: [0:v][0:a][1:v][1:a]...concat=n=N:v=1:a=1
        inputs: list[str] = []
        filter_parts: list[str] = []
        for i, seg in enumerate(segment_files):
            inputs.extend(["-i", seg])
            filter_parts.append(f"[{i}:v][{i}:a]")
        filter_str = (
            "".join(filter_parts)
            + f"concat=n={n}:v=1:a=1[v][a_raw];"
            + "[a_raw]loudnorm=I=-16:TP=-1.5:LRA=11[a]"
        )

        # Write to temp file first, validate, then atomic rename
        base, ext = os.path.splitext(final_path)
        tmp_concat = f"{base}.tmp.{os.getpid()}{ext}"
        try:
            run([
                "ffmpeg", "-y",
                *inputs,
                "-filter_complex", filter_str,
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "128k",
                "-movflags", "+faststart",
                tmp_concat,
            ], "FFmpeg concat", timeout=900)

            # Validate the output before replacing
            probe_result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "stream=codec_type,duration",
                 "-of", "json", tmp_concat],
                capture_output=True, text=True, timeout=30,
            )
            if probe_result.returncode != 0 or not probe_result.stdout.strip():
                logger.error("ERROR: Concat output failed ffprobe validation (missing moov atom?)")
                sys.exit(1)

            streams = json.loads(probe_result.stdout).get("streams", [])
            durations = {s["codec_type"]: float(s.get("duration", 0)) for s in streams}
            v_dur = durations.get("video", 0)
            a_dur = durations.get("audio", 0)

            if v_dur <= 0:
                logger.error("ERROR: Concat output has no video stream")
                sys.exit(1)

            if v_dur > 0 and a_dur > 0:
                ratio = max(v_dur, a_dur) / min(v_dur, a_dur)
                if ratio > 1.05:
                    logger.warning(f"WARNING: A/V duration mismatch — video={v_dur:.1f}s, "
                                   f"audio={a_dur:.1f}s, ratio={ratio:.2f}")

            # Validation passed — atomic replace
            os.replace(tmp_concat, final_path)
        except BaseException:
            if os.path.exists(tmp_concat):
                os.remove(tmp_concat)
            raise

    # Summary
    size_bytes = os.path.getsize(final_path)
    if size_bytes >= 1024 * 1024:
        size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        size_str = f"{size_bytes / 1024:.0f} KB"

    # Get total duration
    total_duration = get_audio_duration(final_path)
    duration_str = f"{int(total_duration // 60)}:{int(total_duration % 60):02d}"

    logger.info(f"\nOK: Rendered {final_filename} ({size_str}, {duration_str})")
    logger.info(f"Path: {final_path}")
    logger.info(f"Sections: {len(episode.sections)}")

    # Register in episodes.json
    register_episode(
        title=episode.title,
        template_path=ep_path,
        video_path=final_path,
        brand=args.brand,
        duration_sec=int(total_duration),
        section_count=len(episode.sections),
    )
    logger.info(f"Registered in episodes.json")

    # Step 4: Render branding suite (intro, card, outro)
    logger.info(f"\n[branding] Rendering episode branding suite ...")

    sched_date = current_sched["date"] if current_sched else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    branding_cmd = [
        "python3", os.path.join(SCRIPT_DIR, "render_episode_branding.py"),
        "--episode", slug,
        "--title", episode.title,
        "--topic", episode.sections[0].title if episode.sections else episode.title,
        "--date", sched_date,
        "--time", "2:00 PM ET",
        "--brand", args.brand,
    ]
    if series:
        branding_cmd += ["--series", series]
    if next_ep:
        branding_cmd += ["--next-title", next_ep.get("topic", "")]
        branding_cmd += ["--next-topic", next_ep.get("topic", "")]
        # Smart outro: only pass date if next episode is in a DIFFERENT series
        # (same series = "Up Next" transition, different series = full goodbye outro)
        if last_in_series:
            branding_cmd += ["--next-date", next_ep.get("date", "")]

    try:
        run(branding_cmd, "Branding suite render", timeout=600)
        logger.info(f"Branding suite rendered for {slug}")
    except Exception as e:
        logger.warning(f"WARNING: Branding suite render failed: {e}")
        # Don't fail the whole episode render if branding fails


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
