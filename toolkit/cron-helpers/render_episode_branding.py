#!/usr/bin/env python3
"""Render full branding suite for an episode (intro, card, outro).

Usage:
  python3 render_episode_branding.py \
    --episode "python-for-beginners" \
    --title "Python for Beginners" \
    --topic "Getting started with Python programming" \
    --date "2026-02-07" \
    --time "2:00 PM ET" \
    --next-title "React Hooks 101" \
    --next-date "Feb 10, 2026" \
    --next-topic "Modern React state management" \
    --brand scripthammer

Outputs to /home/node/clawd-twitch/renders/:
  - {episode}-intro-{date}.mp4
  - {episode}-card-{date}.mp4
  - {episode}-outro-{date}.mp4
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

REMOTION_DIR = os.environ.get("REMOTION_DIR", "/app/remotion")
RENDERS_DIR = os.environ.get("RENDERS_DIR", "/home/node/clawd-twitch/renders")
ENTRY_POINT = "src/index.ts"


def render_composition(
    composition: str,
    props: dict,
    output_path: str,
    dry_run: bool = False,
) -> str | None:
    """Render a single composition and return the output path."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    cmd = [
        "npx", "remotion", "render",
        ENTRY_POINT,
        composition,
        output_path,
        "--props", json.dumps(props),
        "--timeout", "120000",
    ]

    if dry_run:
        print(f"[DRY RUN] Would render: {composition}")
        print(f"  Props: {json.dumps(props, indent=2)}")
        print(f"  Output: {output_path}")
        return output_path

    print(f"Rendering {composition} → {os.path.basename(output_path)} ...")
    result = subprocess.run(
        cmd,
        cwd=REMOTION_DIR,
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode != 0:
        print(f"ERROR: Render failed for {composition}", file=sys.stderr)
        if result.stderr:
            lines = result.stderr.strip().split("\n")
            for line in lines[-10:]:
                print(f"  {line}", file=sys.stderr)
        return None

    if not os.path.exists(output_path):
        print(f"ERROR: Output file not found at {output_path}", file=sys.stderr)
        return None

    size_bytes = os.path.getsize(output_path)
    size_str = f"{size_bytes / 1024:.0f} KB" if size_bytes < 1024 * 1024 else f"{size_bytes / (1024 * 1024):.1f} MB"
    print(f"  OK: {os.path.basename(output_path)} ({size_str})")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Render episode branding suite")
    parser.add_argument("--episode", required=True, help="Episode slug (e.g., python-for-beginners)")
    parser.add_argument("--title", required=True, help="Episode title")
    parser.add_argument("--topic", default="", help="Episode topic/description")
    parser.add_argument("--date", required=True, help="Episode date (e.g., 2026-02-07)")
    parser.add_argument("--time", default="2:00 PM ET", help="Episode time")
    parser.add_argument("--next-title", default="", help="Next episode title (optional)")
    parser.add_argument("--next-date", default="", help="Next episode date (optional)")
    parser.add_argument("--next-topic", default="", help="Next episode topic (optional)")
    parser.add_argument("--brand", default="scripthammer", choices=["turtlewolfe", "scripthammer"])
    parser.add_argument("--series", default="", help="Series slug for topic folder (e.g., docker)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be rendered")
    args = parser.parse_args()

    # Use brand-specific composition prefix
    prefix = "SH-" if args.brand == "scripthammer" else ""
    date_slug = args.date.replace("-", "")

    # Create episode subdirectory under series folder
    if args.series:
        episode_dir = os.path.join(RENDERS_DIR, args.series, args.episode)
    else:
        episode_dir = os.path.join(RENDERS_DIR, args.episode)
    os.makedirs(episode_dir, exist_ok=True)

    rendered_files = []

    # 1. Render intro (uses StreamIntro with episode title)
    intro_props = {
        "brand": args.brand,
        "episodeTitle": args.title,
    }
    intro_output = render_composition(
        f"{prefix}StreamIntro",
        intro_props,
        os.path.join(episode_dir, f"intro-{date_slug}.mp4"),
        dry_run=args.dry_run,
    )
    if intro_output:
        rendered_files.append(("intro", intro_output))

    # 2. Render episode card
    card_props = {
        "brand": args.brand,
        "title": args.title,
        "date": args.date,
        "time": args.time,
        "topic": args.topic,
    }
    card_output = render_composition(
        f"{prefix}EpisodeCard",
        card_props,
        os.path.join(episode_dir, f"card-{date_slug}.mp4"),
        dry_run=args.dry_run,
    )
    if card_output:
        rendered_files.append(("card", card_output))

    # 3. Render outro with next episode teaser
    outro_props = {
        "brand": args.brand,
        "currentEpisodeTitle": args.title,
    }
    if args.next_title:
        outro_props["nextEpisodeTitle"] = args.next_title
    if args.next_date:
        # Format: "Feb 10, 2026 • 2:00 PM ET"
        outro_props["nextEpisodeDate"] = f"{args.next_date} • {args.time}"
    if args.next_topic:
        outro_props["nextEpisodeTopic"] = args.next_topic

    outro_output = render_composition(
        f"{prefix}EpisodeOutro",
        outro_props,
        os.path.join(episode_dir, f"outro-{date_slug}.mp4"),
        dry_run=args.dry_run,
    )
    if outro_output:
        rendered_files.append(("outro", outro_output))

    # Summary
    print()
    print("=" * 50)
    if args.dry_run:
        print("DRY RUN COMPLETE")
    else:
        print(f"BRANDING SUITE RENDERED: {args.episode}")
        for kind, path in rendered_files:
            print(f"  {kind}: {os.path.basename(path)}")
    print("=" * 50)

    return 0 if len(rendered_files) == 3 or args.dry_run else 1


if __name__ == "__main__":
    sys.exit(main())
