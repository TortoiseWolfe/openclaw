#!/usr/bin/env python3
"""Hacker News story fetcher for market-relevant tech news.

Fetches top HN stories and filters for AI/tech/market relevance,
matching against watchlist symbols.
"""

import json
import re
import sys
import time
import urllib.request

from content_security import detect_suspicious, sanitize_field
from news_matching import match_symbols

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"
HN_TOP_STORIES = f"{HN_API_BASE}/topstories.json"
HN_ITEM_URL = HN_API_BASE + "/item/{id}.json"
HN_STORIES_TO_CHECK = 30
HN_ITEM_DELAY = 0.1

HN_TECH_KEYWORDS = [
    "AI", "GPU", "NVIDIA", "semiconductor", "data center",
    "machine learning", "LLM", "OpenAI", "Anthropic",
    "cloud computing", "power grid", "chip", "transformer",
    "neural network", "deep learning", "inference",
]


def _fetch_json(url, timeout=15):
    """Fetch JSON from a URL."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "OpenClaw/1.0",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def fetch_hackernews(watchlist_symbols):
    """Fetch top HN stories and filter for AI/tech/market relevance.

    Returns dict with stories_checked, stories_matched, matched list.
    """
    result = {
        "stories_checked": 0,
        "stories_matched": 0,
        "matched": [],
        "error": None,
    }

    try:
        story_ids = _fetch_json(HN_TOP_STORIES)
        story_ids = story_ids[:HN_STORIES_TO_CHECK]
    except Exception as e:
        result["error"] = f"Failed to fetch top stories: {e}"
        print(f"  HN: FAILED ({e})", file=sys.stderr)
        return result

    for story_id in story_ids:
        try:
            time.sleep(HN_ITEM_DELAY)
            item = _fetch_json(HN_ITEM_URL.format(id=story_id))
            result["stories_checked"] += 1

            title = item.get("title", "")
            url = item.get("url", "")
            score = item.get("score", 0)
            comments = item.get("descendants", 0)

            if not title:
                continue

            if detect_suspicious(title):
                continue

            search_text = f"{title} {url}"

            matched_keywords = [
                kw for kw in HN_TECH_KEYWORDS
                if re.search(r'\b' + re.escape(kw) + r'\b',
                             search_text, re.IGNORECASE)
            ]

            matched_syms = match_symbols(search_text, watchlist_symbols)

            if matched_keywords or matched_syms:
                result["matched"].append({
                    "title": sanitize_field(title, max_len=300),
                    "url": url or (
                        f"https://news.ycombinator.com/item?id="
                        f"{story_id}"),
                    "hn_score": score,
                    "comments": comments,
                    "matched_symbols": matched_syms,
                    "relevance_keywords": matched_keywords[:5],
                })

        except Exception as e:
            print(f"  HN item {story_id}: error ({e})",
                  file=sys.stderr)

    result["stories_matched"] = len(result["matched"])
    print(f"  HN: {result['stories_checked']} checked, "
          f"{result['stories_matched']} matched")
    return result
