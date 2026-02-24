#!/usr/bin/env python3
"""Sync Twitch schedule segment titles with schedule.md.

Runs daily before stream time. Finds today's scheduled episodes from
schedule.md and updates the matching Twitch schedule segment titles to
show the actual series and episode content for the day.

Non-Affiliate channels can only create recurring segments, so titles
must be updated dynamically to match the rotating content schedule.
"""

import sys
import time
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, "/app/toolkit/cron-helpers")

from parse_episode import parse_schedule, _normalize_topic
from twitch_client import (
    _helix_get,
    get_broadcaster_id,
    update_schedule_segment,
)

ET = ZoneInfo("America/New_York")

SERIES_NAMES = {
    "docker": "Docker",
    "python": "Python",
    "react": "React",
    "script": "ScriptHammer",
    "git": "Git",
    "typescript": "TypeScript",
    "nodejs": "Node.js",
    "ai-dev": "AI-Assisted Dev",
    "linux": "Linux",
    "nextjs": "Next.js",
    "postgres": "PostgreSQL",
    "css": "CSS",
    "html": "HTML & Accessibility",
    "javascript": "JavaScript",
    "tailwind": "Tailwind CSS",
    "testing": "Testing",
    "apis": "APIs & Integration",
    "devops": "DevOps & CI/CD",
    "supabase": "Supabase",
    "dsa": "Data Structures & Algorithms",
    "career": "Career Dev",
    "design": "Design for Devs",
    "mongodb": "MongoDB",
    "react-native": "React Native",
    "security": "Web Security",
    "performance": "Performance",
    "pwa": "Progressive Web Apps",
}


def _build_title(episodes: list[dict]) -> str:
    """Build a Twitch segment title from a list of episodes for one date."""
    if not episodes:
        return "Live Coding"
    series_key = episodes[0].get("series", "")
    series_name = SERIES_NAMES.get(series_key, series_key.title())
    topics = [ep["topic"] for ep in episodes]
    # Strip series prefix from topic names for brevity
    short_topics = []
    for t in topics:
        for prefix in [f"{series_name} ", "ScriptHammer "]:
            if t.startswith(prefix):
                t = t[len(prefix):]
        short_topics.append(t)
    topic_list = ", ".join(short_topics)
    title = f"{series_name} | {topic_list}"
    if len(title) > 140:
        title = title[:137] + "..."
    return title


def sync_today() -> None:
    """Update Twitch schedule segments for today's content."""
    now_et = datetime.now(ET)
    today_str = now_et.strftime("%Y-%m-%d")
    print(f"Syncing Twitch schedule for {today_str}...")

    # Get today's episodes from schedule.md
    schedule = parse_schedule()
    today_eps = [ep for ep in schedule if ep["date"] == today_str]
    if not today_eps:
        print(f"No episodes scheduled for {today_str}, nothing to sync.")
        return

    title = _build_title(today_eps)

    print(f"Today's content: {title}")

    # Find today's Twitch segments
    bid = get_broadcaster_id()
    data = _helix_get(f"/schedule?broadcaster_id={bid}&first=25")
    segments = data.get("data", {}).get("segments", [])

    updated = 0
    for seg in segments:
        start_utc = seg["start_time"]
        dt = datetime.fromisoformat(start_utc.replace("Z", "+00:00")).astimezone(ET)
        seg_date = dt.strftime("%Y-%m-%d")

        if seg_date != today_str:
            continue

        # Skip RPG game night segments
        cat = seg.get("category", {})
        if cat and cat.get("id") == "509664":
            continue

        slot = "AM" if dt.hour < 12 else "PM"
        if seg["title"] != title:
            print(f"  Updating {slot} segment: {seg['title'][:40]} -> {title[:40]}")
            update_schedule_segment(seg["id"], title=title)
            updated += 1
            time.sleep(0.3)
        else:
            print(f"  {slot} segment already correct")

    print(f"Updated {updated} segments.")


def sync_week() -> None:
    """Update Twitch schedule segments for the next 7 days."""
    now_et = datetime.now(ET)
    schedule = parse_schedule()

    # Group schedule by date
    by_date: dict[str, list[dict]] = defaultdict(list)
    for ep in schedule:
        by_date[ep["date"]].append(ep)

    bid = get_broadcaster_id()

    # Fetch enough segments to cover the week
    all_segments = []
    cursor = ""
    for _ in range(5):
        path = f"/schedule?broadcaster_id={bid}&first=25"
        if cursor:
            path += f"&after={cursor}"
        try:
            data = _helix_get(path)
        except Exception:
            break
        segs = data.get("data", {}).get("segments", [])
        if not segs:
            break
        all_segments.extend(segs)
        cursor = data.get("pagination", {}).get("cursor", "")
        if not cursor:
            break
        time.sleep(0.3)

    updated = 0
    for seg in all_segments:
        start_utc = seg["start_time"]
        dt = datetime.fromisoformat(start_utc.replace("Z", "+00:00")).astimezone(ET)
        seg_date = dt.strftime("%Y-%m-%d")
        days_ahead = (dt.date() - now_et.date()).days
        if days_ahead < 0 or days_ahead > 7:
            continue

        # Skip RPG segments
        cat = seg.get("category", {})
        if cat and cat.get("id") == "509664":
            continue

        eps = by_date.get(seg_date, [])
        if not eps:
            continue

        title = _build_title(eps)

        slot = "AM" if dt.hour < 12 else "PM"
        if seg["title"] != title:
            print(f"  {seg_date} {slot}: {seg['title'][:40]} -> {title[:40]}")
            try:
                update_schedule_segment(seg["id"], title=title)
                updated += 1
                time.sleep(0.3)
            except Exception as e:
                print(f"    ERROR: {e}")
        else:
            print(f"  {seg_date} {slot}: already correct")

    print(f"\nUpdated {updated} segments for the next 7 days.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sync Twitch schedule with schedule.md")
    parser.add_argument(
        "--week", action="store_true", help="Sync next 7 days instead of just today"
    )
    args = parser.parse_args()

    if args.week:
        sync_week()
    else:
        sync_today()
