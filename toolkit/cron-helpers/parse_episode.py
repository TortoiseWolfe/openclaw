#!/usr/bin/env python3
"""Parse episode markdown templates into structured data for rendering."""

import os
import re
from dataclasses import dataclass, field


@dataclass
class EpisodeSection:
    number: int
    title: str
    time_min: int
    bullets: list[str]
    code_block: str | None = None
    code_language: str | None = None


@dataclass
class Episode:
    title: str
    level: str
    duration_min: int
    sections: list[EpisodeSection] = field(default_factory=list)
    key_takeaways: list[str] = field(default_factory=list)
    engagement_points: list[str] = field(default_factory=list)


def parse_episode(markdown: str) -> Episode:
    """Parse an episode markdown template into an Episode object."""
    lines = markdown.split("\n")

    title = ""
    level = ""
    duration_min = 30
    sections: list[EpisodeSection] = []
    key_takeaways: list[str] = []
    engagement_points: list[str] = []

    # State machine
    current_zone = "header"  # header | outline | takeaways | engagement
    current_section: EpisodeSection | None = None
    in_code_block = False
    code_lines: list[str] = []
    code_lang: str | None = None

    for line in lines:
        stripped = line.strip()

        # Inside a fenced code block — only look for closing fence
        if in_code_block:
            if stripped.startswith("```"):
                in_code_block = False
                if current_section:
                    current_section.code_block = "\n".join(code_lines)
                    current_section.code_language = code_lang
            else:
                code_lines.append(line.rstrip())
            continue

        # Episode title
        if stripped.startswith("# ") and not stripped.startswith("## "):
            title = stripped[2:].strip()
            continue

        # Metadata
        if stripped.startswith("**Level:**"):
            level = stripped.replace("**Level:**", "").strip()
            continue
        if stripped.startswith("**Duration:**"):
            m = re.search(r"(\d+)", stripped)
            if m:
                duration_min = int(m.group(1))
            continue
        if stripped.startswith("**Prerequisites:**"):
            continue

        # Zone transitions
        if stripped == "## Outline":
            current_zone = "outline"
            continue
        if stripped == "## Key Takeaways":
            _flush_section(current_section, sections, code_lines, code_lang)
            current_section = None
            current_zone = "takeaways"
            continue
        if stripped.startswith("## Chat Engagement"):
            current_zone = "engagement"
            continue

        # Outline: section headings
        if current_zone == "outline" and stripped.startswith("### "):
            _flush_section(current_section, sections, code_lines, code_lang)
            code_lines = []
            code_lang = None
            current_section = _parse_section_heading(stripped)
            continue

        # Code block opening fence
        if current_zone == "outline" and current_section and stripped.startswith("```"):
            in_code_block = True
            code_lang = stripped[3:].strip() or None
            code_lines = []
            continue

        # Bullets in sections
        if current_zone == "outline" and current_section and stripped.startswith("- "):
            current_section.bullets.append(_add_oxford_comma(stripped[2:]))
            continue

        # Key takeaways
        if current_zone == "takeaways" and stripped.startswith("- "):
            key_takeaways.append(stripped[2:])
            continue

        # Engagement points
        if current_zone == "engagement" and stripped.startswith("- "):
            engagement_points.append(stripped[2:])
            continue

    # Flush final section
    _flush_section(current_section, sections, code_lines, code_lang)

    return Episode(
        title=title,
        level=level,
        duration_min=duration_min,
        sections=sections,
        key_takeaways=key_takeaways,
        engagement_points=engagement_points,
    )


def _flush_section(
    section: EpisodeSection | None,
    sections: list[EpisodeSection],
    code_lines: list[str],
    code_lang: str | None,
) -> None:
    if section is None:
        return
    if code_lines and section.code_block is None:
        section.code_block = "\n".join(code_lines)
        section.code_language = code_lang
    sections.append(section)


def _parse_section_heading(line: str) -> EpisodeSection:
    """Parse '### 1. Why Docker? (5 min)' into an EpisodeSection."""
    text = line.lstrip("#").strip()
    # Extract number
    num_match = re.match(r"(\d+)\.\s*", text)
    number = int(num_match.group(1)) if num_match else 1
    if num_match:
        text = text[num_match.end():]
    # Extract time
    time_match = re.search(r"\((\d+)\s*min\)", text)
    time_min = int(time_match.group(1)) if time_match else 5
    if time_match:
        text = text[:time_match.start()].strip()
    return EpisodeSection(number=number, title=text, time_min=time_min, bullets=[])


def _add_oxford_comma(text: str) -> str:
    """Insert 'and' before the last item in comma-separated lists (3+ items)."""
    commas = [m.start() for m in re.finditer(r',\s', text)]
    if len(commas) < 2:
        return text
    last_comma = commas[-1]
    after = text[last_comma + 1:].lstrip()
    if re.match(r'\b(and|or)\b', after):
        return text  # already has conjunction
    return text[:last_comma + 1] + " and" + text[last_comma + 1:]


def _clean_bullet(bullet: str) -> str:
    """Clean markdown formatting from a bullet for TTS narration."""
    text = bullet
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)  # bold
    text = re.sub(r"`(.+?)`", r"\1", text)  # inline code
    text = text.replace(" -- ", ". ")  # em dash to sentence break
    text = text.replace("--", ". ")
    text = re.sub(r"^Analogy:\s*", "Think of it this way. ", text)
    # Ensure bullet ends with sentence punctuation so TTS pauses between bullets
    text = text.rstrip()
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _auto_bold_leading_term(bullet: str) -> str:
    """Auto-bold leading key terms that aren't already marked up.

    Detects patterns like 'Term -- definition' or 'Term: definition' at the
    start of a bullet and wraps the leading term in **bold** markdown.
    """
    if bullet.startswith("**"):
        return bullet  # already bold
    # "Key Term -- rest" or "Key Term: rest" (1-3 capitalized words)
    m = re.match(r"^([A-Z][A-Za-z.]+(?:\s+[A-Za-z.]+){0,2})\s*(--|:)\s*", bullet)
    if m:
        term = m.group(1)
        sep = m.group(2)
        rest = bullet[m.end():]
        return f"**{term}{sep}** {rest}" if sep == ":" else f"**{term}** {sep} {rest}"
    return bullet


def parse_bullet_parts(bullet: str) -> list[dict]:
    """Parse markdown bold/code into structured parts for Remotion rendering.

    Returns a list of dicts: [{"text": "...", "style": "text"|"bold"|"code"}, ...]
    """
    bullet = _auto_bold_leading_term(bullet)
    parts: list[dict] = []
    # Match bold, inline code, or bare URLs (domain.tld/path patterns)
    pattern = r"(\*\*(.+?)\*\*|`(.+?)`|\b((?:https?://|[a-z0-9-]+\.(?:com|org|net|io|dev|sh|co))\S*))"
    last_end = 0
    for m in re.finditer(pattern, bullet):
        if m.start() > last_end:
            plain = bullet[last_end : m.start()]
            if plain:
                plain = plain.replace(" -- ", "\u2014").replace("--", "\u2014")
                parts.append({"text": plain, "style": "text"})
        if m.group(2):  # **bold**
            parts.append({"text": m.group(2), "style": "bold"})
        elif m.group(3):  # `code`
            parts.append({"text": m.group(3), "style": "code"})
        elif m.group(4):  # bare URL
            parts.append({"text": m.group(4), "style": "code"})
        last_end = m.end()
    remaining = bullet[last_end:]
    if remaining:
        remaining = remaining.replace(" -- ", "\u2014").replace("--", "\u2014")
        parts.append({"text": remaining, "style": "text"})
    return parts if parts else [{"text": bullet, "style": "text"}]


def bullets_to_narration(section: EpisodeSection) -> str:
    """Convert a section's title and bullets into narration text for TTS."""
    parts = [f"{section.title}."]
    for bullet in section.bullets:
        parts.append(_clean_bullet(bullet))
    return " ".join(parts)


def get_bullet_char_offsets(section: EpisodeSection) -> list[int]:
    """Return character offsets where each bullet starts in the narration string.

    Mirrors the text construction in bullets_to_narration() so offsets
    align exactly with the TTS input text.
    """
    offsets: list[int] = []
    pos = len(section.title) + 2  # "Title. " → title + ". " (period + space before first bullet)
    for bullet in section.bullets:
        offsets.append(pos)
        cleaned = _clean_bullet(bullet)
        pos += len(cleaned) + 1  # +1 for the " " join separator
    return offsets


SCHEDULE_PATH = "/home/node/clawd-twitch/schedule.md"


def parse_schedule() -> list[dict]:
    """Parse schedule.md into a list of episode dicts."""
    if not os.path.exists(SCHEDULE_PATH):
        return []

    with open(SCHEDULE_PATH) as f:
        lines = f.readlines()

    episodes = []
    in_table = False
    for line in lines:
        line = line.strip()
        if line.startswith("| Date"):
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and line.startswith("|"):
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) >= 6:
                episodes.append({
                    "date": parts[0],
                    "time": parts[1],
                    "topic": parts[2],
                    "series": parts[3],
                    "type": parts[4],
                    "status": parts[5],
                })
            elif len(parts) >= 5:
                # Backward compat: no series column
                episodes.append({
                    "date": parts[0],
                    "time": parts[1],
                    "topic": parts[2],
                    "series": "",
                    "type": parts[3],
                    "status": parts[4],
                })
    return episodes


def get_next_episode(current_topic: str) -> dict | None:
    """Get the next episode after the current one (any status).

    Args:
        current_topic: The topic name (e.g., "Python for Beginners")

    Returns:
        Dict with date, time, topic, series, type, status or None.
    """
    schedule = parse_schedule()
    found_current = False
    for ep in schedule:
        if found_current:
            return ep
        if ep["topic"].lower() == current_topic.lower():
            found_current = True
    return None


def get_series_episodes(series: str) -> list[dict]:
    """Return all episodes in a series, ordered by date."""
    return [ep for ep in parse_schedule() if ep.get("series") == series]


def is_last_in_series(topic: str) -> bool:
    """Check if this episode is the last in its series."""
    schedule = parse_schedule()
    current = next((ep for ep in schedule if ep["topic"].lower() == topic.lower()), None)
    if not current or not current.get("series"):
        return True
    series_eps = get_series_episodes(current["series"])
    return series_eps[-1]["topic"].lower() == topic.lower()


def topic_to_slug(topic: str) -> str:
    """Convert topic name to slug (e.g., 'Python for Beginners' -> 'python-for-beginners')."""
    slug = re.sub(r"[^a-z0-9\s-]", "", topic.lower().replace("&", "and"))
    return re.sub(r"\s+", "-", slug.strip())


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 parse_episode.py <episode.md>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        ep = parse_episode(f.read())

    print(f"Title: {ep.title}")
    print(f"Level: {ep.level}")
    print(f"Duration: {ep.duration_min} min")
    print(f"Sections: {len(ep.sections)}")
    for s in ep.sections:
        narration = bullets_to_narration(s)
        print(f"  {s.number}. {s.title} ({s.time_min} min) — {len(s.bullets)} bullets, "
              f"code={'yes' if s.code_block else 'no'}")
        print(f"     Narration ({len(narration)} chars): {narration[:100]}...")
    print(f"Takeaways: {len(ep.key_takeaways)}")
    print(f"Engagement: {len(ep.engagement_points)}")
