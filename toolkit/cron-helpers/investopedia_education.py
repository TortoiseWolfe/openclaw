#!/usr/bin/env python3
"""Batch education scraper for Investopedia technical analysis articles.

Fetches curated TA articles (indicators, chart patterns, candlesticks,
trading strategies), extracts content, and saves summaries to
trading-data/education/article-summaries/.

Usage:
    python3 investopedia_education.py           # fetch all pending
    python3 investopedia_education.py --limit 5 # fetch up to 5
    python3 investopedia_education.py --dry-run  # list articles without fetching
"""

import os
import re
import sys
import time
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from content_security import detect_suspicious

# ── Paths ────────────────────────────────────────────────────────────

# Auto-detect: Docker container vs host
if os.path.isdir("/home/node/repos/Trading/education"):
    EDU_DIR = "/home/node/repos/Trading/education"
else:
    EDU_DIR = os.path.join(os.path.dirname(__file__), "..", "..",
                           "trading-data", "education")
    EDU_DIR = os.path.abspath(EDU_DIR)

SUMMARIES_DIR = os.path.join(EDU_DIR, "article-summaries")

# ── Article index ────────────────────────────────────────────────────

ARTICLES = [
    # ── Technical Indicators ──
    {"title": "Relative Strength Index (RSI)", "url": "https://www.investopedia.com/terms/r/rsi.asp", "category": "indicators"},
    {"title": "MACD Indicator", "url": "https://www.investopedia.com/terms/m/macd.asp", "category": "indicators"},
    {"title": "Bollinger Bands", "url": "https://www.investopedia.com/terms/b/bollingerbands.asp", "category": "indicators"},
    {"title": "Simple Moving Average (SMA)", "url": "https://www.investopedia.com/terms/s/sma.asp", "category": "indicators"},
    {"title": "Exponential Moving Average (EMA)", "url": "https://www.investopedia.com/terms/e/ema.asp", "category": "indicators"},
    {"title": "Stochastic Oscillator", "url": "https://www.investopedia.com/terms/s/stochasticoscillator.asp", "category": "indicators"},
    {"title": "Average Directional Index (ADX)", "url": "https://www.investopedia.com/terms/a/adx.asp", "category": "indicators"},
    {"title": "Average True Range (ATR)", "url": "https://www.investopedia.com/terms/a/atr.asp", "category": "indicators"},
    {"title": "On-Balance Volume (OBV)", "url": "https://www.investopedia.com/terms/o/onbalancevolume.asp", "category": "indicators"},
    {"title": "Commodity Channel Index (CCI)", "url": "https://www.investopedia.com/terms/c/commoditychannelindex.asp", "category": "indicators"},
    {"title": "Williams %R", "url": "https://www.investopedia.com/terms/w/williamsr.asp", "category": "indicators"},
    {"title": "Ichimoku Cloud", "url": "https://www.investopedia.com/terms/i/ichimoku-cloud.asp", "category": "indicators"},
    {"title": "VWAP", "url": "https://www.investopedia.com/terms/v/vwap.asp", "category": "indicators"},
    {"title": "Fibonacci Retracement", "url": "https://www.investopedia.com/terms/f/fibonacciretracement.asp", "category": "indicators"},
    {"title": "Pivot Points", "url": "https://www.investopedia.com/terms/p/pivotpoint.asp", "category": "indicators"},
    {"title": "Parabolic SAR", "url": "https://www.investopedia.com/terms/p/parabolicindicator.asp", "category": "indicators"},
    {"title": "Money Flow Index (MFI)", "url": "https://www.investopedia.com/terms/m/mfi.asp", "category": "indicators"},
    {"title": "Rate of Change (ROC)", "url": "https://www.investopedia.com/terms/r/rateofchange.asp", "category": "indicators"},
    {"title": "Aroon Indicator", "url": "https://www.investopedia.com/terms/a/aroon.asp", "category": "indicators"},
    {"title": "Keltner Channel", "url": "https://www.investopedia.com/terms/k/keltnerchannel.asp", "category": "indicators"},
    {"title": "Standard Deviation", "url": "https://www.investopedia.com/terms/s/standarddeviation.asp", "category": "indicators"},
    {"title": "Volume Weighted Average Price", "url": "https://www.investopedia.com/articles/trading/11/trading-with-vwap-mvwap.asp", "category": "indicators"},

    # ── Chart Patterns ──
    {"title": "Head and Shoulders Pattern", "url": "https://www.investopedia.com/terms/h/head-shoulders.asp", "category": "chart_patterns"},
    {"title": "Double Top and Bottom", "url": "https://www.investopedia.com/terms/d/doubletop.asp", "category": "chart_patterns"},
    {"title": "Double Bottom", "url": "https://www.investopedia.com/terms/d/doublebottom.asp", "category": "chart_patterns"},
    {"title": "Triangle Patterns", "url": "https://www.investopedia.com/terms/t/triangle.asp", "category": "chart_patterns"},
    {"title": "Ascending Triangle", "url": "https://www.investopedia.com/terms/a/ascendingtriangle.asp", "category": "chart_patterns"},
    {"title": "Descending Triangle", "url": "https://www.investopedia.com/terms/d/descendingtriangle.asp", "category": "chart_patterns"},
    {"title": "Symmetrical Triangle", "url": "https://www.investopedia.com/terms/s/symmetricaltriangle.asp", "category": "chart_patterns"},
    {"title": "Wedge Pattern", "url": "https://www.investopedia.com/terms/w/wedge.asp", "category": "chart_patterns"},
    {"title": "Flag Pattern", "url": "https://www.investopedia.com/terms/f/flag.asp", "category": "chart_patterns"},
    {"title": "Pennant Pattern", "url": "https://www.investopedia.com/terms/p/pennant.asp", "category": "chart_patterns"},
    {"title": "Cup and Handle", "url": "https://www.investopedia.com/terms/c/cupandhandle.asp", "category": "chart_patterns"},
    {"title": "Rounding Bottom", "url": "https://www.investopedia.com/terms/r/roundingbottom.asp", "category": "chart_patterns"},
    {"title": "Channel Pattern", "url": "https://www.investopedia.com/terms/c/channel.asp", "category": "chart_patterns"},
    {"title": "Broadening Formation", "url": "https://www.investopedia.com/terms/b/broadeningformation.asp", "category": "chart_patterns"},
    {"title": "Rectangle Pattern", "url": "https://www.investopedia.com/terms/r/rectangle.asp", "category": "chart_patterns"},
    {"title": "Gap Trading", "url": "https://www.investopedia.com/terms/g/gap.asp", "category": "chart_patterns"},
    {"title": "Triple Top and Bottom", "url": "https://www.investopedia.com/terms/t/tripletop.asp", "category": "chart_patterns"},

    # ── Candlestick Patterns ──
    {"title": "Candlestick Chart", "url": "https://www.investopedia.com/terms/c/candlestick.asp", "category": "candlesticks"},
    {"title": "Doji Candlestick", "url": "https://www.investopedia.com/terms/d/doji.asp", "category": "candlesticks"},
    {"title": "Hammer Candlestick", "url": "https://www.investopedia.com/terms/h/hammer.asp", "category": "candlesticks"},
    {"title": "Hanging Man", "url": "https://www.investopedia.com/terms/h/hangingman.asp", "category": "candlesticks"},
    {"title": "Engulfing Pattern", "url": "https://www.investopedia.com/terms/b/bullishengulfingpattern.asp", "category": "candlesticks"},
    {"title": "Bearish Engulfing Pattern", "url": "https://www.investopedia.com/terms/b/bearishengulfingp.asp", "category": "candlesticks"},
    {"title": "Morning Star", "url": "https://www.investopedia.com/terms/m/morningstar.asp", "category": "candlesticks"},
    {"title": "Evening Star", "url": "https://www.investopedia.com/terms/e/eveningstar.asp", "category": "candlesticks"},
    {"title": "Shooting Star", "url": "https://www.investopedia.com/terms/s/shootingstar.asp", "category": "candlesticks"},
    {"title": "Spinning Top", "url": "https://www.investopedia.com/terms/s/spinning-top.asp", "category": "candlesticks"},
    {"title": "Harami Pattern", "url": "https://www.investopedia.com/terms/b/bullishharami.asp", "category": "candlesticks"},
    {"title": "Three White Soldiers", "url": "https://www.investopedia.com/terms/t/three_white_soldiers.asp", "category": "candlesticks"},
    {"title": "Three Black Crows", "url": "https://www.investopedia.com/terms/t/three_black_crows.asp", "category": "candlesticks"},
    {"title": "Marubozu", "url": "https://www.investopedia.com/terms/m/marubozo.asp", "category": "candlesticks"},
    {"title": "Inverted Hammer", "url": "https://www.investopedia.com/terms/i/inverted-hammer.asp", "category": "candlesticks"},
    {"title": "Piercing Pattern", "url": "https://www.investopedia.com/terms/piercing-pattern.asp", "category": "candlesticks"},
    {"title": "Dark Cloud Cover", "url": "https://www.investopedia.com/terms/d/darkcloud.asp", "category": "candlesticks"},
    {"title": "Tweezer Tops and Bottoms", "url": "https://www.investopedia.com/terms/t/tweezer.asp", "category": "candlesticks"},

    # ── Trading Concepts ──
    {"title": "Technical Analysis", "url": "https://www.investopedia.com/terms/t/technicalanalysis.asp", "category": "concepts"},
    {"title": "Support and Resistance", "url": "https://www.investopedia.com/trading/support-and-resistance-basics/", "category": "concepts"},
    {"title": "Trend Analysis", "url": "https://www.investopedia.com/terms/t/trendanalysis.asp", "category": "concepts"},
    {"title": "Breakout Trading", "url": "https://www.investopedia.com/terms/b/breakout.asp", "category": "concepts"},
    {"title": "Reversal Pattern", "url": "https://www.investopedia.com/terms/r/reversal.asp", "category": "concepts"},
    {"title": "Continuation Pattern", "url": "https://www.investopedia.com/terms/c/continuationpattern.asp", "category": "concepts"},
    {"title": "Divergence", "url": "https://www.investopedia.com/terms/d/divergence.asp", "category": "concepts"},
    {"title": "Overbought", "url": "https://www.investopedia.com/terms/o/overbought.asp", "category": "concepts"},
    {"title": "Oversold", "url": "https://www.investopedia.com/terms/o/oversold.asp", "category": "concepts"},
    {"title": "Volume Analysis", "url": "https://www.investopedia.com/articles/technical/02/010702.asp", "category": "concepts"},
    {"title": "Price Action Trading", "url": "https://www.investopedia.com/articles/active-trading/110714/introduction-price-action-trading-strategies.asp", "category": "concepts"},
    {"title": "Multiple Time Frame Analysis", "url": "https://www.investopedia.com/articles/trading/07/timeframes.asp", "category": "concepts"},

    # ── Risk Management ──
    {"title": "Risk-Reward Ratio", "url": "https://www.investopedia.com/terms/r/riskrewardratio.asp", "category": "risk_management"},
    {"title": "Position Sizing", "url": "https://www.investopedia.com/terms/p/positionsizing.asp", "category": "risk_management"},
    {"title": "Stop-Loss Order", "url": "https://www.investopedia.com/terms/s/stop-lossorder.asp", "category": "risk_management"},
    {"title": "Trailing Stop", "url": "https://www.investopedia.com/terms/t/trailingstop.asp", "category": "risk_management"},
    {"title": "Risk Management", "url": "https://www.investopedia.com/terms/r/riskmanagement.asp", "category": "risk_management"},
    {"title": "Drawdown", "url": "https://www.investopedia.com/terms/d/drawdown.asp", "category": "risk_management"},
    {"title": "Sharpe Ratio", "url": "https://www.investopedia.com/terms/s/sharperatio.asp", "category": "risk_management"},
    {"title": "Maximum Drawdown", "url": "https://www.investopedia.com/terms/m/maximum-drawdown-mdd.asp", "category": "risk_management"},
    {"title": "Kelly Criterion", "url": "https://www.investopedia.com/articles/trading/04/091504.asp", "category": "risk_management"},

    # ── Trading Strategies ──
    {"title": "Swing Trading", "url": "https://www.investopedia.com/terms/s/swingtrading.asp", "category": "strategies"},
    {"title": "Day Trading", "url": "https://www.investopedia.com/terms/d/daytrader.asp", "category": "strategies"},
    {"title": "Scalping", "url": "https://www.investopedia.com/terms/s/scalping.asp", "category": "strategies"},
    {"title": "Position Trading", "url": "https://www.investopedia.com/terms/p/positiontrader.asp", "category": "strategies"},
    {"title": "Momentum Trading", "url": "https://www.investopedia.com/terms/m/momentum.asp", "category": "strategies"},
    {"title": "Mean Reversion", "url": "https://www.investopedia.com/terms/m/meanreversion.asp", "category": "strategies"},
    {"title": "Trend Following", "url": "https://www.investopedia.com/terms/t/trendtrading.asp", "category": "strategies"},
    {"title": "Breakout Strategy", "url": "https://www.investopedia.com/articles/trading/06/daytradingretail.asp", "category": "strategies"},
    {"title": "Moving Average Crossover", "url": "https://www.investopedia.com/articles/active-trading/052014/how-use-moving-average-buy-stocks.asp", "category": "strategies"},
    {"title": "Carry Trade", "url": "https://www.investopedia.com/terms/c/currencycarrytrade.asp", "category": "strategies"},

    # ── Forex-Specific ──
    {"title": "Forex Market Overview", "url": "https://www.investopedia.com/terms/f/forex.asp", "category": "forex"},
    {"title": "Currency Pairs", "url": "https://www.investopedia.com/terms/c/currencypair.asp", "category": "forex"},
    {"title": "Pip Value", "url": "https://www.investopedia.com/terms/p/pip.asp", "category": "forex"},
    {"title": "Lot Size", "url": "https://www.investopedia.com/terms/s/standard-lot.asp", "category": "forex"},
    {"title": "Leverage in Forex", "url": "https://www.investopedia.com/terms/l/leverage.asp", "category": "forex"},
    {"title": "Margin Trading", "url": "https://www.investopedia.com/terms/m/margin.asp", "category": "forex"},
    {"title": "Forex Spread", "url": "https://www.investopedia.com/terms/s/spread.asp", "category": "forex"},
    {"title": "Currency Correlation", "url": "https://www.investopedia.com/terms/c/currency-trading-forex-tips.asp", "category": "forex"},
]


# ── Content extractor (regex-based for Investopedia) ─────────────────

def _strip_tags(html):
    """Strip HTML tags and decode entities."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = text.replace("&#39;", "'").replace("&#43;", "+")
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&nbsp;", " ")
    # Decode numeric entities
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    return text


def extract_investopedia(html, max_words=2000):
    """Extract article content from Investopedia HTML using regex.

    Investopedia uses heavy JS hydration that confuses HTMLParser.
    Instead, we extract <p> tags from within the article-body-content section.
    """
    # Try to isolate the article body section
    article_match = re.search(
        r'class="[^"]*article-body-content[^"]*"[^>]*>(.*?)(?=<div[^>]*class="[^"]*article-sources)',
        html, re.DOTALL
    )
    if not article_match:
        # Fallback: find the mntl-sc-page section
        article_match = re.search(
            r'id="mntl-sc-page_1-0"[^>]*>(.*?)(?=</article>)',
            html, re.DOTALL
        )
    if not article_match:
        # Last resort: extract all p tags from the whole page
        section = html
    else:
        section = article_match.group(1)

    # Extract paragraphs
    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", section, re.DOTALL)

    # Strip tags, filter noise
    texts = []
    for p in paragraphs:
        text = _strip_tags(p).strip()
        text = re.sub(r"\s+", " ", text)
        # Skip very short paragraphs (nav items, labels)
        if len(text) < 20:
            continue
        # Skip author bios and repeated boilerplate
        if "Chartered Market Technician" in text or "has been an active investor" in text:
            continue
        texts.append(text)

    content = " ".join(texts)
    words = content.split()
    return " ".join(words[:max_words])


# ── Helpers ──────────────────────────────────────────────────────────

def slugify(text):
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text.strip("-")


def fetch_page(url):
    req = Request(url, headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urlopen(req, timeout=30) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset)


def summary_exists(title, today):
    slug = slugify(title)
    filename = f"investopedia-{slug}-{today.isoformat()}.md"
    return os.path.exists(os.path.join(SUMMARIES_DIR, filename))


def write_summary(article, content, today):
    os.makedirs(SUMMARIES_DIR, exist_ok=True)
    slug = slugify(article["title"])
    filename = f"investopedia-{slug}-{today.isoformat()}.md"
    path = os.path.join(SUMMARIES_DIR, filename)

    lines = [
        f"# {article['title']}",
        "",
        f"**Source**: {article['url']}",
        f"**Date**: {today.isoformat()}",
        f"**Provider**: Investopedia",
        f"**Category**: {article['category']}",
        "",
        "## Key Concepts",
        "",
        content,
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
            limit = int(sys.argv[i + 1])

    print(f"Investopedia Education Scraper — {len(ARTICLES)} articles indexed")
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
            content = extract_investopedia(html, max_words=2000)

            if len(content.split()) < 50:
                print(f"  {article['title']:45s}: SKIP (too little content)")
                errors += 1
                continue

            path = write_summary(article, content, today)
            word_count = len(content.split())
            print(f"  {article['title']:45s}: {word_count:4d} words")

            flags = detect_suspicious(content)
            if flags:
                print(f"    [security] Suspicious: {flags}", file=sys.stderr)

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
