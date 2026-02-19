#!/usr/bin/env python3
"""Render a Remotion composition to video or still image.

Usage:
  python3 render_video.py --composition EpisodeCard \\
    --props '{"title":"Docker Basics","date":"2026-02-10","time":"8 PM ET","topic":"Containers"}'

  python3 render_video.py --composition EpisodeCard --format png --frame 90

  python3 render_video.py --composition StreamIntro --format mp4

Outputs to /home/node/clawd-twitch/renders/<composition>-<timestamp>.<ext>
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

REMOTION_DIR = "/app/remotion"
OUTPUT_DIR = "/home/node/clawd-twitch/renders"
ENTRY_POINT = "src/index.ts"


def main():
    parser = argparse.ArgumentParser(description="Render Remotion composition")
    parser.add_argument("--composition", required=True, help="Composition ID (e.g. EpisodeCard)")
    parser.add_argument("--props", default="{}", help="JSON props string")
    parser.add_argument("--format", default="mp4", choices=["mp4", "webm", "png", "gif"])
    parser.add_argument("--frame", type=int, default=None, help="Render single frame (for stills)")
    args = parser.parse_args()

    # Validate props JSON
    try:
        json.loads(args.props)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in --props: {e}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    ext = args.format
    filename = f"{args.composition}-{timestamp}.{ext}"
    output_path = os.path.join(OUTPUT_DIR, filename)

    # Use 'still' for single-frame renders, 'render' for video
    if args.frame is not None:
        cmd = [
            "npx", "remotion", "still",
            ENTRY_POINT,
            args.composition,
            output_path,
            "--props", args.props,
            "--frame", str(args.frame),
        ]
    else:
        cmd = [
            "npx", "remotion", "render",
            ENTRY_POINT,
            args.composition,
            output_path,
            "--props", args.props,
            "--timeout", "120000",
        ]

    print(f"Rendering {args.composition} → {filename} ...")
    result = subprocess.run(
        cmd,
        cwd=REMOTION_DIR,
        capture_output=True,
        text=True,
        timeout=600,
    )

    if result.returncode != 0:
        print(f"ERROR: Render failed (exit {result.returncode})", file=sys.stderr)
        if result.stderr:
            # Print last 20 lines of stderr for diagnostics
            lines = result.stderr.strip().split("\n")
            for line in lines[-20:]:
                print(f"  {line}", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(output_path):
        print(f"ERROR: Output file not found at {output_path}", file=sys.stderr)
        sys.exit(1)

    size_bytes = os.path.getsize(output_path)
    if size_bytes >= 1024 * 1024:
        size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        size_str = f"{size_bytes / 1024:.0f} KB"

    print(f"OK: Rendered {filename} ({size_str})")
    print(f"Path: {output_path}")


if __name__ == "__main__":
    main()
