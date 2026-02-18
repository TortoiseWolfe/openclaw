#!/usr/bin/env python3
"""Validate episode template duration and content density.

Usage:
  python3 validate_episode.py <episode.md> [<episode.md> ...]
  python3 validate_episode.py /home/node/clawd-twitch/episodes/*.md
"""

import sys
from pathlib import Path

# Import parse_episode from same directory
sys.path.insert(0, str(Path(__file__).parent))
from parse_episode import Episode, EpisodeSection, bullets_to_narration, parse_episode

WORDS_PER_MINUTE = 150
# Rendered video is ~2x narration time due to Remotion transitions,
# fade-in/out, bullet animation timing, and intro segment.
# Measured: 1283 words @ 150wpm = 8.6 min narration → 17:59 rendered.
RENDER_MULTIPLIER = 2.0
MAX_BULLETS_PER_SECTION = 14
MIN_BULLETS_PER_SECTION = 6
MAX_CODE_LINES = 12
TARGET_MIN = 12
TARGET_MAX = 25


def validate(ep: Episode, path: str) -> list[str]:
    """Validate an episode and return warnings."""
    warnings: list[str] = []
    total_words = 0
    total_bullets = 0

    print(f"\n{'=' * 60}")
    print(f"  {ep.title}  ({path})")
    print(f"  Level: {ep.level}  |  Claimed: {ep.duration_min} min")
    print(f"{'=' * 60}")
    print(f"  {'#':<4} {'Section':<30} {'Bullets':>7} {'Words':>7} {'~Min':>6}")
    print(f"  {'-'*4} {'-'*30} {'-'*7} {'-'*7} {'-'*6}")

    for s in ep.sections:
        narration = bullets_to_narration(s)
        words = len(narration.split())
        est_min = words / WORDS_PER_MINUTE
        total_words += words
        total_bullets += len(s.bullets)

        flag = ""
        if len(s.bullets) < MIN_BULLETS_PER_SECTION:
            flag = " ⚠ sparse"
            warnings.append(f"Section {s.number} '{s.title}': only {len(s.bullets)} bullets (min {MIN_BULLETS_PER_SECTION})")
        if len(s.bullets) > MAX_BULLETS_PER_SECTION:
            flag = " ⚠ dense"
            warnings.append(f"Section {s.number} '{s.title}': {len(s.bullets)} bullets (max {MAX_BULLETS_PER_SECTION})")
        if s.code_block:
            lines = len(s.code_block.split("\n"))
            if lines > MAX_CODE_LINES:
                flag += " ⚠ code"
                warnings.append(f"Section {s.number} '{s.title}': code block {lines} lines (max {MAX_CODE_LINES})")

        print(f"  {s.number:<4} {s.title:<30} {len(s.bullets):>7} {words:>7} {est_min:>5.1f}{flag}")

    narration_min = total_words / WORDS_PER_MINUTE
    total_min = narration_min * RENDER_MULTIPLIER
    print(f"  {'-'*4} {'-'*30} {'-'*7} {'-'*7} {'-'*6}")
    print(f"  {'':4} {'TOTAL':<30} {total_bullets:>7} {total_words:>7} {narration_min:>5.1f}")
    print(f"\n  Narration: {narration_min:.1f} min  |  Rendered estimate: ~{total_min:.0f} min")

    if total_min < TARGET_MIN:
        warnings.append(f"Estimated {total_min:.1f} min — under {TARGET_MIN} min target")
    if total_min > TARGET_MAX:
        warnings.append(f"Estimated {total_min:.1f} min — over {TARGET_MAX} min target")

    if warnings:
        print(f"\n  Warnings:")
        for w in warnings:
            print(f"    ⚠ {w}")
    else:
        print(f"\n  ✓ All checks passed")

    return warnings


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 validate_episode.py <episode.md> [...]", file=sys.stderr)
        sys.exit(1)

    all_warnings: list[str] = []
    for path in sys.argv[1:]:
        with open(path) as f:
            ep = parse_episode(f.read())
        all_warnings.extend(validate(ep, path))

    print()
    if all_warnings:
        print(f"Total: {len(all_warnings)} warning(s)")
        sys.exit(1)
    else:
        print("All episodes validated successfully.")


if __name__ == "__main__":
    main()
