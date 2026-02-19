#!/usr/bin/env python3
"""Fetch supplementary news from free sources: RSS feeds, BabyPips, Hacker News.

Complements the Alpha Vantage NEWS_SENTIMENT pull with broader coverage.
Runs at 8:50 AM ET, between AV sentiment (8:45) and trade decisions (9:00).

Decomposed modules:
  - news_matching.py    — symbol matching, headline sentiment
  - news_rss.py         — RSS feed fetching & parsing
  - news_babypips.py    — BabyPips daily recap extraction
  - news_hackernews.py  — Hacker News story filtering

Usage (from Docker):
  python3 market_news_supplementary.py
"""

import json
import os
import sys
import time
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trading_common import load_watchlist, atomic_json_write, NEWS_DIR

# Re-export for backwards compatibility (tests, daily analysis)
from news_matching import (
    match_symbols, headline_sentiment, build_symbol_set,
    SYMBOL_NAMES, _CASE_SENSITIVE_SYMBOLS, _ALIAS_ONLY_SYMBOLS,
    BULLISH_WORDS, BEARISH_WORDS,
)
from news_rss import parse_rss_xml, fetch_all_rss
from news_babypips import _normalize_pair, fetch_babypips_recap
from news_hackernews import fetch_hackernews

SOURCE_DELAY = 10  # seconds between major sources


# ── Aggregation ──────────────────────────────────────────────────────

def build_symbol_mentions(rss_data, babypips_data, hn_data):
    """Aggregate per-symbol mention counts across all sources."""
    mentions = {}

    def _add(symbol, source, sentiment=None):
        if symbol not in mentions:
            mentions[symbol] = {
                "total_mentions": 0,
                "sources": set(),
                "sentiments": [],
            }
        mentions[symbol]["total_mentions"] += 1
        mentions[symbol]["sources"].add(source)
        if sentiment:
            mentions[symbol]["sentiments"].append(sentiment)

    for article in rss_data.get("matched", []):
        for sym in article.get("matched_symbols", []):
            _add(sym, "rss", article.get("headline_sentiment"))

    for pair in babypips_data.get("pairs_mentioned", []):
        _add(pair, "babypips")

    for story in hn_data.get("matched", []):
        for sym in story.get("matched_symbols", []):
            _add(sym, "hackernews")

    for data in mentions.values():
        data["sources"] = sorted(data["sources"])
        sentiments = data.pop("sentiments", [])
        bull = sentiments.count("bullish")
        bear = sentiments.count("bearish")
        if bull > bear:
            data["net_sentiment"] = "bullish"
        elif bear > bull:
            data["net_sentiment"] = "bearish"
        else:
            data["net_sentiment"] = "neutral"

    return mentions


def build_summary(rss_data, babypips_data, hn_data, mentions):
    """Build overall summary."""
    total = (rss_data.get("articles_matched", 0)
             + len(babypips_data.get("key_headlines", []))
             + hn_data.get("stories_matched", 0))

    sources_ok = ((1 if rss_data.get("feeds_succeeded", 0) > 0 else 0)
                  + (1 if babypips_data.get("fetched") else 0)
                  + (1 if hn_data.get("error") is None else 0))

    most_mentioned = (
        max(mentions, key=lambda s: mentions[s]["total_mentions"])
        if mentions else None
    )

    all_sentiments = [a.get("headline_sentiment", "neutral")
                      for a in rss_data.get("matched", [])]
    bull = all_sentiments.count("bullish")
    bear = all_sentiments.count("bearish")
    if bull > bear + 2:
        overall = "Bullish"
    elif bull > bear:
        overall = "Somewhat_Bullish"
    elif bear > bull + 2:
        overall = "Bearish"
    elif bear > bull:
        overall = "Somewhat_Bearish"
    else:
        overall = "Neutral"

    return {
        "total_articles": total,
        "sources_succeeded": sources_ok,
        "most_mentioned": most_mentioned,
        "headline_sentiment": overall,
    }


# ── Persistence ──────────────────────────────────────────────────────

def save_supplementary(date_str, data):
    """Atomic JSON write to news directory."""
    path = os.path.join(NEWS_DIR, f"supplementary-{date_str}.json")
    atomic_json_write(path, data)
    return path


def load_supplementary(date_str):
    """Load previously saved supplementary data. Returns dict or None."""
    path = os.path.join(NEWS_DIR, f"supplementary-{date_str}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


# ── Markdown rendering ───────────────────────────────────────────────

def _escape_pipe(text):
    """Escape pipe chars for markdown tables."""
    return text.replace("|", "\\|") if text else ""


def format_supplementary_markdown(data):
    """Render supplementary news as markdown lines for daily analysis."""
    sources = data.get("sources", {})
    has_rss = bool(sources.get("rss", {}).get("matched"))
    has_bp = sources.get("babypips", {}).get("fetched", False)
    has_hn = bool(sources.get("hackernews", {}).get("matched"))
    if not (has_rss or has_bp or has_hn):
        return []

    lines = ["## Supplementary News", ""]

    rss = sources.get("rss", {})
    matched = rss.get("matched", [])
    if matched:
        lines.append(
            f"**RSS feeds** ({rss.get('feeds_succeeded', 0)}/"
            f"{rss.get('feeds_attempted', 0)} feeds, "
            f"{rss.get('articles_matched', 0)} relevant):")
        lines.append("")
        lines.append("| Source | Headline | Symbols | Sentiment |")
        lines.append("|--------|----------|---------|-----------|")
        for a in matched[:10]:
            syms = _escape_pipe(", ".join(a.get("matched_symbols", [])))
            title = _escape_pipe(a["title"][:60])
            source = _escape_pipe(a.get("source", ""))
            sent = _escape_pipe(a.get("headline_sentiment", ""))
            lines.append(
                f"| {source} | {title} | {syms} | {sent} |")
        lines.append("")

    bp = data.get("sources", {}).get("babypips", {})
    if bp.get("fetched"):
        lines.append("**BabyPips Daily Recap:**")
        if bp.get("pairs_mentioned"):
            lines.append(
                f"- Pairs mentioned: "
                f"{', '.join(bp['pairs_mentioned'])}")
        cs = bp.get("currency_strength", {})
        if cs.get("strongest"):
            lines.append(
                f"- Strongest: {cs['strongest']} / "
                f"Weakest: {cs['weakest']}")
        if bp.get("economic_events"):
            lines.append(
                f"- Events: "
                f"{', '.join(bp['economic_events'][:5])}")
        lines.append("")

    hn = data.get("sources", {}).get("hackernews", {})
    hn_matched = hn.get("matched", [])
    if hn_matched:
        lines.append(
            f"**Hacker News** "
            f"({hn.get('stories_matched', 0)} relevant):")
        lines.append("")
        for story in hn_matched[:5]:
            syms = ", ".join(
                story.get("matched_symbols", [])) or "tech"
            kws = ", ".join(
                story.get("relevance_keywords", [])[:3])
            lines.append(
                f"- [{story.get('hn_score', 0)} pts] "
                f"{_escape_pipe(story['title'][:60])} ({syms}) [{kws}]")
        lines.append("")

    summary = data.get("summary", {})
    if summary.get("total_articles", 0) > 0:
        parts = [
            f"**Supplementary overall:** "
            f"{summary.get('headline_sentiment', 'N/A')}",
        ]
        if summary.get("most_mentioned"):
            parts.append(
                f"Most mentioned: {summary['most_mentioned']}")
        parts.append(
            f"{summary.get('total_articles', 0)} items from "
            f"{summary.get('sources_succeeded', 0)} sources")
        lines.append(" | ".join(parts))
        lines.append("")

    return lines


# ── Main ─────────────────────────────────────────────────────────────

def main():
    today = date.today()
    today_str = today.isoformat()

    existing = load_supplementary(today_str)
    if existing:
        print(f"Supplementary news already collected for {today_str}")
        summary = existing.get("summary", {})
        print(f"  {summary.get('total_articles', 0)} items, "
              f"sentiment: {summary.get('headline_sentiment', '?')}")
        return

    watchlist = load_watchlist()
    symbols = build_symbol_set(watchlist)
    print(f"Fetching supplementary news for {today_str} "
          f"({len(symbols)} symbols)")

    # Source 1: RSS feeds
    print("Fetching RSS feeds...")
    rss_data = fetch_all_rss(symbols)

    time.sleep(SOURCE_DELAY)

    # Source 2: BabyPips daily recap
    print("Fetching BabyPips recap...")
    babypips_data = fetch_babypips_recap(today)

    time.sleep(SOURCE_DELAY)

    # Source 3: Hacker News
    print("Fetching Hacker News...")
    hn_data = fetch_hackernews(symbols)

    # Aggregate
    mentions = build_symbol_mentions(rss_data, babypips_data, hn_data)
    summary = build_summary(rss_data, babypips_data, hn_data, mentions)

    data = {
        "date": today_str,
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "rss": rss_data,
            "babypips": babypips_data,
            "hackernews": hn_data,
        },
        "symbol_mentions": mentions,
        "summary": summary,
    }

    path = save_supplementary(today_str, data)
    print(f"\nSaved to {path}")
    print(f"  {summary['total_articles']} items from "
          f"{summary['sources_succeeded']} sources")
    print(f"  Sentiment: {summary['headline_sentiment']}")
    if summary.get("most_mentioned"):
        print(f"  Most mentioned: {summary['most_mentioned']}")


if __name__ == "__main__":
    main()
