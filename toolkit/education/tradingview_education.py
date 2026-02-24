#!/usr/bin/env python3
"""Batch education scraper for TradingView support knowledge base articles.

Fetches technical analysis articles from TradingView's /support/solutions/
knowledge base (indicators, chart patterns, candlesticks). Saves summaries
to trading-data/education/article-summaries/.

Usage:
    python3 tradingview_education.py           # fetch all pending
    python3 tradingview_education.py --limit 5 # fetch up to 5
    python3 tradingview_education.py --dry-run  # list articles without fetching
"""

import os
import re
import sys
import time
from datetime import date
from urllib.error import HTTPError, URLError

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/app/toolkit/cron-helpers")
from content_security import detect_suspicious, wrap_external
from education_common import fetch_page, slugify, ContentExtractor

# ── Paths ────────────────────────────────────────────────────────────

if os.path.isdir("/home/node/repos/Trading/education"):
    EDU_DIR = "/home/node/repos/Trading/education"
else:
    EDU_DIR = os.path.join(os.path.dirname(__file__), "..", "..",
                           "trading-data", "education")
    EDU_DIR = os.path.abspath(EDU_DIR)

SUMMARIES_DIR = os.path.join(EDU_DIR, "article-summaries")

# ── Article index ────────────────────────────────────────────────────
# TradingView support articles: /support/solutions/43000XXXXXX-slug/

ARTICLES = [
    # ── Technical Analysis Overview ──
    {"title": "Technical Analysis Essentials", "url": "https://www.tradingview.com/support/solutions/43000759577-the-technical-analysis-essentials-with-tradingview/", "category": "overview"},
    {"title": "How to Read Chart Patterns", "url": "https://www.tradingview.com/support/solutions/43000759289-how-to-read-chart-patterns/", "category": "overview"},

    # ── Indicators ──
    {"title": "Bollinger Bands (BB)", "url": "https://www.tradingview.com/support/solutions/43000501840-bollinger-bands-bb/", "category": "indicators"},
    {"title": "MACD Indicator", "url": "https://www.tradingview.com/support/solutions/43000502344-moving-average-convergence-divergence-macd-indicator/", "category": "indicators"},
    {"title": "Moving Averages", "url": "https://www.tradingview.com/support/solutions/43000502589-moving-averages/", "category": "indicators"},
    {"title": "Stochastic RSI", "url": "https://www.tradingview.com/support/solutions/43000502333-stochastic-rsi-stoch-rsi/", "category": "indicators"},
    {"title": "RSI (Relative Strength Index)", "url": "https://www.tradingview.com/support/solutions/43000502338-relative-strength-index-rsi/", "category": "indicators"},
    {"title": "VWAP", "url": "https://www.tradingview.com/support/solutions/43000502018-volume-weighted-average-price-vwap/", "category": "indicators"},
    {"title": "Average True Range (ATR)", "url": "https://www.tradingview.com/support/solutions/43000501823-average-true-range-atr/", "category": "indicators"},
    {"title": "Ichimoku Cloud", "url": "https://www.tradingview.com/support/solutions/43000589152-ichimoku-cloud/", "category": "indicators"},
    {"title": "Parabolic SAR", "url": "https://www.tradingview.com/support/solutions/43000502597-parabolic-sar-sar/", "category": "indicators"},
    {"title": "On-Balance Volume (OBV)", "url": "https://www.tradingview.com/support/solutions/43000502593-on-balance-volume-obv/", "category": "indicators"},
    {"title": "Commodity Channel Index (CCI)", "url": "https://www.tradingview.com/support/solutions/43000502001-commodity-channel-index-cci/", "category": "indicators"},
    {"title": "Williams %R", "url": "https://www.tradingview.com/support/solutions/43000501985-williams-r-r/", "category": "indicators"},
    {"title": "Average Directional Index (ADX)", "url": "https://www.tradingview.com/support/solutions/43000589099-average-directional-index-adx/", "category": "indicators"},
    {"title": "Accumulation/Distribution", "url": "https://www.tradingview.com/support/solutions/43000501770-accumulation-distribution-a-d/", "category": "indicators"},
    {"title": "Aroon", "url": "https://www.tradingview.com/support/solutions/43000501801-aroon/", "category": "indicators"},
    {"title": "Chaikin Money Flow", "url": "https://www.tradingview.com/support/solutions/43000501974-chaikin-money-flow-cmf/", "category": "indicators"},
    {"title": "Donchian Channels", "url": "https://www.tradingview.com/support/solutions/43000502253-donchian-channels-dc/", "category": "indicators"},
    {"title": "Keltner Channels", "url": "https://www.tradingview.com/support/solutions/43000502266-keltner-channels-kc/", "category": "indicators"},
    {"title": "Money Flow Index (MFI)", "url": "https://www.tradingview.com/support/solutions/43000502348-money-flow-mfi/", "category": "indicators"},
    {"title": "Stochastic Oscillator", "url": "https://www.tradingview.com/support/solutions/43000502332-stochastic-stoch/", "category": "indicators"},
    {"title": "Volume Profile", "url": "https://www.tradingview.com/support/solutions/43000502040-volume-profile-indicators-basic-concepts/", "category": "indicators"},
    {"title": "Pivot Points Standard", "url": "https://www.tradingview.com/support/solutions/43000521824-pivot-points-standard/", "category": "indicators"},
    {"title": "Hull Moving Average", "url": "https://www.tradingview.com/support/solutions/43000589149-hull-moving-average/", "category": "indicators"},
    {"title": "Fibonacci Retracement", "url": "https://www.tradingview.com/support/solutions/43000590035-fibonacci-retracement/", "category": "indicators"},
    {"title": "Technical Ratings", "url": "https://www.tradingview.com/support/solutions/43000614331-technical-ratings/", "category": "indicators"},
    {"title": "Bollinger Bands %B", "url": "https://www.tradingview.com/support/solutions/43000501842-bollinger-bands-b-bb-b/", "category": "indicators"},
    {"title": "Bollinger BandWidth", "url": "https://www.tradingview.com/support/solutions/43000501841-bollinger-bandwidth-bbw/", "category": "indicators"},
    {"title": "MACD Strategy", "url": "https://www.tradingview.com/support/solutions/43000669137-macd-strategy/", "category": "indicators"},

    # ── Chart Patterns ──
    {"title": "All Chart Patterns", "url": "https://www.tradingview.com/support/solutions/43000706927-all-chart-patterns/", "category": "chart_patterns"},
    {"title": "Head and Shoulders", "url": "https://www.tradingview.com/support/solutions/43000653213-chart-pattern-head-and-shoulders/", "category": "chart_patterns"},
    {"title": "Inverse Head and Shoulders", "url": "https://www.tradingview.com/support/solutions/43000653214-chart-pattern-inverse-head-and-shoulders/", "category": "chart_patterns"},
    {"title": "Double Top", "url": "https://www.tradingview.com/support/solutions/43000653211-chart-pattern-double-top/", "category": "chart_patterns"},
    {"title": "Double Bottom", "url": "https://www.tradingview.com/support/solutions/43000653210-chart-pattern-double-bottom/", "category": "chart_patterns"},
    {"title": "Triangle", "url": "https://www.tradingview.com/support/solutions/43000653217-chart-pattern-triangle/", "category": "chart_patterns"},
    {"title": "Falling Wedge", "url": "https://www.tradingview.com/support/solutions/43000653208-chart-pattern-falling-wedge/", "category": "chart_patterns"},
    {"title": "Rising Wedge", "url": "https://www.tradingview.com/support/solutions/43000653216-chart-pattern-rising-wedge/", "category": "chart_patterns"},
    {"title": "Bullish Flag", "url": "https://www.tradingview.com/support/solutions/43000653207-chart-pattern-bullish-flag/", "category": "chart_patterns"},
    {"title": "Bearish Flag", "url": "https://www.tradingview.com/support/solutions/43000653206-chart-pattern-bearish-flag/", "category": "chart_patterns"},
    {"title": "Bullish Pennant", "url": "https://www.tradingview.com/support/solutions/43000653205-chart-pattern-bullish-pennant/", "category": "chart_patterns"},
    {"title": "Bearish Pennant", "url": "https://www.tradingview.com/support/solutions/43000653204-chart-pattern-bearish-pennant/", "category": "chart_patterns"},
    {"title": "Triple Top", "url": "https://www.tradingview.com/support/solutions/43000653218-chart-pattern-triple-top/", "category": "chart_patterns"},
    {"title": "Triple Bottom", "url": "https://www.tradingview.com/support/solutions/43000653219-chart-pattern-triple-bottom/", "category": "chart_patterns"},
    {"title": "Rectangle", "url": "https://www.tradingview.com/support/solutions/43000653215-chart-pattern-rectangle/", "category": "chart_patterns"},
    {"title": "Auto Chart Patterns", "url": "https://www.tradingview.com/support/solutions/43000653209-auto-chart-patterns/", "category": "chart_patterns"},

    # ── Candlestick Patterns ──
    {"title": "Introduction to Candlestick Charts", "url": "https://www.tradingview.com/support/solutions/43000745269-introduction-to-candlestick-charts-and-patterns/", "category": "candlesticks"},
    {"title": "Automatic Candlestick Pattern Detection", "url": "https://www.tradingview.com/support/solutions/43000650498-automatic-candlestick-pattern-detection/", "category": "candlesticks"},

    # ── Drawing Tools ──
    {"title": "Trend Lines", "url": "https://www.tradingview.com/support/solutions/43000505088-trend-line/", "category": "drawing_tools"},
    {"title": "Fibonacci Retracement Tool", "url": "https://www.tradingview.com/support/solutions/43000518158-fib-retracement/", "category": "drawing_tools"},
    {"title": "Pitchfork", "url": "https://www.tradingview.com/support/solutions/43000518141-pitchfork/", "category": "drawing_tools"},
    {"title": "Gann Fan", "url": "https://www.tradingview.com/support/solutions/43000518151-gann-fan/", "category": "drawing_tools"},
]


# fetch_page, slugify, ContentExtractor imported from education_common


def _make_tv_extractor():
    """Create a ContentExtractor configured for TradingView support articles."""
    return ContentExtractor(
        article_classes={"article", "content", "solution-article"},
        article_ids={"article-body"},
    )


def summary_exists(title, today):
    slug = slugify(title)
    filename = f"tradingview-{slug}-{today.isoformat()}.md"
    return os.path.exists(os.path.join(SUMMARIES_DIR, filename))


def write_summary(article, content, today):
    os.makedirs(SUMMARIES_DIR, exist_ok=True)
    slug = slugify(article["title"])
    filename = f"tradingview-{slug}-{today.isoformat()}.md"
    path = os.path.join(SUMMARIES_DIR, filename)

    lines = [
        f"# {article['title']}",
        "",
        f"**Source**: {article['url']}",
        f"**Date**: {today.isoformat()}",
        f"**Provider**: TradingView",
        f"**Category**: {article['category']}",
        "",
        "## Key Concepts",
        "",
        wrap_external(content, source="tradingview"),
        "",
    ]

    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


# ── Main ─────────────────────────────────────────────────────────────

def main():
    today = date.today()
    dry_run = "--dry-run" in sys.argv
    limit = None
    for i, arg in enumerate(sys.argv):
        if arg == "--limit" and i + 1 < len(sys.argv):
            try:
                limit = int(sys.argv[i + 1])
            except ValueError:
                print(f"ERROR: --limit requires an integer, got '{sys.argv[i + 1]}'", file=sys.stderr)
                sys.exit(1)

    print(f"TradingView Education Scraper — {len(ARTICLES)} articles indexed")
    print(f"Output: {SUMMARIES_DIR}")

    if dry_run:
        for i, a in enumerate(ARTICLES, 1):
            exists = "DONE" if summary_exists(a["title"], today) else "pending"
            print(f"  {i:3d}. [{exists:7s}] {a['category']:18s} {a['title']}")
        return

    fetched = 0
    skipped = 0
    errors = 0

    for i, article in enumerate(ARTICLES):
        if limit and fetched >= limit:
            break

        if summary_exists(article["title"], today):
            skipped += 1
            continue

        try:
            html = fetch_page(article["url"])
            parser = _make_tv_extractor()
            parser.feed(html)
            content = parser.get_content(max_words=2000)

            if len(content.split()) < 50:
                print(f"  {article['title']:45s}: SKIP (too little content)")
                errors += 1
                continue

            flags = detect_suspicious(content)
            if flags:
                print(f"  {article['title']:45s}: BLOCKED (suspicious: {flags})",
                      file=sys.stderr)
                errors += 1
                continue

            path = write_summary(article, content, today)
            word_count = len(content.split())
            print(f"  {article['title']:45s}: {word_count:4d} words")

            fetched += 1
            time.sleep(1.5)  # polite delay

        except (HTTPError, URLError) as e:
            print(f"  {article['title']:45s}: ERROR {e}")
            errors += 1
            time.sleep(2)

        except Exception as e:
            print(f"  {article['title']:45s}: ERROR {e}")
            errors += 1

    print(f"\nDone: {fetched} fetched | {skipped} already done | {errors} errors")
    print(f"Total articles: {len(ARTICLES)}")


if __name__ == "__main__":
    main()
