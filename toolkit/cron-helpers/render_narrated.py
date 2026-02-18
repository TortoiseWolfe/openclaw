#!/usr/bin/env python3
"""Render a narrated Remotion composition by combining TTS audio with video via FFmpeg.

Usage:
  python3 render_narrated.py --composition StreamIntro \
    --narration-text "Welcome to TurtleWolfe! Today we're covering Docker Basics."

  python3 render_narrated.py --composition StreamIntro \
    --narration-file /tmp/script.txt --voice en-US-MichelleNeural

Outputs to /home/node/clawd-twitch/renders/<composition>-narrated-<timestamp>.mp4
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = "/home/node/clawd-twitch/renders"


def run(cmd: list[str], label: str, timeout: int = 600) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        print(f"ERROR: {label} failed (exit {result.returncode})", file=sys.stderr)
        if result.stderr:
            for line in result.stderr.strip().split("\n")[-10:]:
                print(f"  {line}", file=sys.stderr)
        sys.exit(1)
    return result


def main():
    parser = argparse.ArgumentParser(description="Render narrated Remotion composition")
    parser.add_argument("--composition", required=True, help="Composition ID (e.g. StreamIntro)")
    parser.add_argument("--narration-text", help="Text to narrate (inline)")
    parser.add_argument("--narration-file", help="Path to text file with narration script")
    parser.add_argument("--voice", default="en-US-GuyNeural", help="Edge TTS voice")
    parser.add_argument("--props", default="{}", help="JSON props for Remotion composition")
    parser.add_argument("--subtitles", action="store_true", help="Generate .vtt subtitles")
    args = parser.parse_args()

    # Resolve narration text
    if args.narration_text:
        narration = args.narration_text
    elif args.narration_file:
        with open(args.narration_file) as f:
            narration = f.read().strip()
    else:
        print("ERROR: Provide --narration-text or --narration-file", file=sys.stderr)
        sys.exit(1)

    if not narration:
        print("ERROR: Narration text is empty", file=sys.stderr)
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = os.path.join(tmpdir, "narration.mp3")
        video_path = os.path.join(tmpdir, "silent.mp4")
        final_path = os.path.join(OUTPUT_DIR, f"{args.composition}-narrated-{timestamp}.mp4")

        # Step 1: Generate TTS audio
        print(f"[1/3] Generating narration ({len(narration)} chars, voice={args.voice}) ...")
        tts_cmd = [
            "python3", os.path.join(SCRIPT_DIR, "generate_narration.py"),
            "--text", narration,
            "--output", audio_path,
            "--voice", args.voice,
        ]
        if args.subtitles:
            tts_cmd.append("--subtitles")
        run(tts_cmd, "TTS generation")

        # Step 2: Render silent video
        print(f"[2/3] Rendering {args.composition} video ...")
        render_cmd = [
            "python3", os.path.join(SCRIPT_DIR, "render_video.py"),
            "--composition", args.composition,
            "--props", args.props,
            "--format", "mp4",
        ]
        run(render_cmd, "Video render")

        # Find the rendered video (render_video.py outputs to OUTPUT_DIR)
        # Move it to tmpdir so we can mux it
        rendered_files = sorted(
            [f for f in os.listdir(OUTPUT_DIR) if f.startswith(args.composition) and f.endswith(".mp4") and "narrated" not in f],
            key=lambda f: os.path.getmtime(os.path.join(OUTPUT_DIR, f)),
            reverse=True,
        )
        if not rendered_files:
            print("ERROR: No rendered video found", file=sys.stderr)
            sys.exit(1)

        latest_render = os.path.join(OUTPUT_DIR, rendered_files[0])
        shutil.move(latest_render, video_path)

        # Step 3: FFmpeg mux audio + video
        print("[3/3] Muxing audio + video ...")
        mux_cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "128k",
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-shortest",
            final_path,
        ]
        run(mux_cmd, "FFmpeg mux")

        # Move subtitles if generated
        if args.subtitles:
            vtt_src = os.path.join(tmpdir, "narration.vtt")
            if os.path.exists(vtt_src):
                vtt_dst = final_path.replace(".mp4", ".vtt")
                shutil.move(vtt_src, vtt_dst)
                print(f"Subtitles: {vtt_dst}")

    size_bytes = os.path.getsize(final_path)
    if size_bytes >= 1024 * 1024:
        size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        size_str = f"{size_bytes / 1024:.0f} KB"

    print(f"OK: Rendered {os.path.basename(final_path)} ({size_str})")
    print(f"Path: {final_path}")


if __name__ == "__main__":
    main()
