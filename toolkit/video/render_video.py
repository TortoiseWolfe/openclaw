#!/usr/bin/env python3
"""Render a Remotion composition to video via the remotion-renderer HTTP API.

Usage:
  python3 render_video.py --composition EpisodeCard \\
    --props '{"title":"Docker Basics","date":"2026-02-10","time":"8 PM ET","topic":"Containers"}'

  python3 render_video.py --composition StreamIntro --format mp4

Outputs to /home/node/clawd-twitch/renders/<composition>-<timestamp>.<ext>

Note: Still image rendering (--frame) is not supported via the HTTP API.
Use the remotion-renderer container directly for stills.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import remotion_client

OUTPUT_DIR = "/home/node/clawd-twitch/renders"
# Path prefix as seen by the remotion-renderer container
REMOTION_RENDERS_PREFIX = "/renders"


def main():
    parser = argparse.ArgumentParser(description="Render Remotion composition")
    parser.add_argument("--composition", required=True, help="Composition ID (e.g. EpisodeCard)")
    parser.add_argument("--props", default="{}", help="JSON props string")
    parser.add_argument("--format", default="mp4", choices=["mp4", "webm"])
    args = parser.parse_args()

    # Validate props JSON
    try:
        props = json.loads(args.props)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in --props: {e}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    ext = args.format
    filename = f"{args.composition}-{timestamp}.{ext}"
    output_path = os.path.join(OUTPUT_DIR, filename)

    # Convert to remotion-renderer container path
    rel = os.path.relpath(output_path, OUTPUT_DIR)
    api_path = f"{REMOTION_RENDERS_PREFIX}/{rel}"

    print(f"Rendering {args.composition} → {filename} ...")
    result = remotion_client.render(args.composition, props, api_path)

    if not result.get("success"):
        print(f"ERROR: Render failed: {result.get('error')}", file=sys.stderr)
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
