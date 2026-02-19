#!/usr/bin/env python3
"""One-time migration: reorganize renders into episode subdirectories.

Usage:
  python3 migrate_renders.py --dry-run    # Preview changes
  python3 migrate_renders.py              # Execute migration
"""

import argparse
import glob
import os
import re
import shutil

RENDERS_DIR = "/home/node/clawd-twitch/renders"
GENERIC_DIR = os.path.join(RENDERS_DIR, "_generic")


def extract_episode_slug(filename: str) -> str | None:
    """Extract episode slug from filename like 'python-for-beginners-20260205-194557.mp4'."""
    # Match pattern: {slug}-{YYYYMMDD}-{HHMMSS}.mp4 or {slug}-{YYYYMMDD}.mp4
    m = re.match(r"^(.+?)-(\d{8})(?:-\d{6})?\.mp4$", filename)
    if m:
        slug = m.group(1)
        # Skip generic branding files
        if slug.startswith("SH-") or slug in ["StreamIntro", "HoldingScreen", "EpisodeCard", "HighlightTitle"]:
            return None
        return slug
    return None


def migrate_files(dry_run: bool = False) -> None:
    """Move episode content to subdirectories, generic to _generic."""
    if not os.path.isdir(RENDERS_DIR):
        print(f"ERROR: {RENDERS_DIR} does not exist")
        return

    # Create _generic directory for fallback branding
    if not dry_run:
        os.makedirs(GENERIC_DIR, exist_ok=True)

    moved = 0
    for filename in os.listdir(RENDERS_DIR):
        if not filename.endswith((".mp4", ".png", ".vtt")):
            continue

        src = os.path.join(RENDERS_DIR, filename)
        if os.path.isdir(src):
            continue

        # Generic branding files -> _generic/
        if filename.startswith("SH-") or filename.startswith("StreamIntro") or \
           filename.startswith("HoldingScreen") or filename.startswith("EpisodeCard") or \
           filename.startswith("HighlightTitle"):
            dst = os.path.join(GENERIC_DIR, filename)
            if dry_run:
                print(f"  [generic] {filename} -> _generic/")
            else:
                shutil.move(src, dst)
            moved += 1
            continue

        # Episode content files -> {slug}/content-{date}.mp4
        slug = extract_episode_slug(filename)
        if slug:
            episode_dir = os.path.join(RENDERS_DIR, slug)
            # Extract date from filename
            m = re.search(r"-(\d{8})", filename)
            date_slug = m.group(1) if m else "unknown"
            ext = os.path.splitext(filename)[1]
            new_filename = f"content-{date_slug}{ext}"
            dst = os.path.join(episode_dir, new_filename)

            if dry_run:
                print(f"  [episode] {filename} -> {slug}/{new_filename}")
            else:
                os.makedirs(episode_dir, exist_ok=True)
                shutil.move(src, dst)
            moved += 1

    print(f"\n{'Would move' if dry_run else 'Moved'} {moved} files")


def main():
    parser = argparse.ArgumentParser(description="Migrate renders to episode subdirectories")
    parser.add_argument("--dry-run", action="store_true", help="Preview without moving files")
    args = parser.parse_args()

    print("=" * 50)
    print("RENDER MIGRATION")
    print("=" * 50)
    print(f"Source: {RENDERS_DIR}")
    print(f"Generic branding: {GENERIC_DIR}")
    print(f"Dry run: {args.dry_run}")
    print()

    migrate_files(dry_run=args.dry_run)

    if not args.dry_run:
        print("\nMigration complete!")
        print("Run render_episode_branding.py for each episode to generate branding assets.")


if __name__ == "__main__":
    main()
