#!/usr/bin/env python3
"""Fetch daily news sentiment for all watchlist assets.

Uses Alpha Vantage NEWS_SENTIMENT API. Batches tickers to minimize
API calls (3 calls for 30 symbols). Saves structured JSON per day.

Forward-looking data collection only -- no influence on trade signals yet.
After months of data, analyze sentiment vs trade outcome correlation.

Usage (from Docker):
  python3 market_news_sentiment.py
"""

import json
import os
import sys
import statistics
import time
import urllib.request
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trading_common import (
    load_watchlist, av_fetch as fetch_url, av_extract_error,
    atomic_json_write, CONFIG_DIR, NEWS_DIR,
    AV_API_KEY as API_KEY, AV_CALLS_PER_MINUTE as CALLS_PER_MINUTE,
)
MAX_ARTICLES_PER_SYMBOL = 3


# -- Sentiment thresholds (Alpha Vantage documented ranges) -----------

def classify_sentiment(score):
    """Map numeric sentiment score to label."""
    if score is None:
        return "No Data"
    if score <= -0.35:
        return "Bearish"
    if score <= -0.15:
        return "Somewhat_Bearish"
    if score < 0.15:
        return "Neutral"
    if score < 0.35:
        return "Somewhat_Bullish"
    return "Bullish"


# -- Watchlist + batching ---------------------------------------------


def build_ticker_batches(watchlist):
    """Group watchlist symbols into batched API calls with correct prefixes.

    Returns list of lists of ticker strings ready for the API.
    """
    stocks = [a["symbol"] for a in watchlist.get("stocks", [])]
    crypto = [f"CRYPTO:{a['symbol']}" for a in watchlist.get("crypto", [])]

    # Forex: AV uses individual currencies, not pairs
    forex_currencies = set()
    for a in watchlist.get("forex", []):
        forex_currencies.add(f"FOREX:{a['from']}")
        forex_currencies.add(f"FOREX:{a['to']}")
    forex = sorted(forex_currencies)

    # Split stocks into batches of ~10, append crypto to last stock batch
    mid = len(stocks) // 2
    batch1 = stocks[:mid]
    batch2 = stocks[mid:] + crypto
    batch3 = forex

    return [b for b in [batch1, batch2, batch3] if b]


# -- API fetching -----------------------------------------------------


def fetch_news_batch(tickers):
    """Call NEWS_SENTIMENT for a batch of tickers.

    tickers: list of strings like ["AAPL", "CRYPTO:BTC", "FOREX:EUR"]
    Returns raw AV response dict.
    """
    return fetch_url({
        "function": "NEWS_SENTIMENT",
        "tickers": ",".join(tickers),
        "sort": "RELEVANCE",
        "limit": "50",
    })


# -- Response parsing -------------------------------------------------

def extract_ticker_sentiments(raw_response):
    """Parse AV NEWS_SENTIMENT response into per-ticker aggregates.

    Returns {ticker: {article_count, avg_sentiment, sentiment_label,
                      avg_relevance, bullish_count, bearish_count,
                      neutral_count, top_articles}}.
    """
    feed = raw_response.get("feed", [])
    if not feed:
        return {}

    # Collect per-ticker article data
    ticker_articles = {}  # ticker -> [(sentiment, relevance, article_info)]
    for article in feed:
        for ts in article.get("ticker_sentiment", []):
            ticker = ts.get("ticker", "")
            if not ticker:
                continue
            score = float(ts.get("ticker_sentiment_score", 0))
            relevance = float(ts.get("relevance_score", 0))
            info = {
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "time_published": article.get("time_published", ""),
                "sentiment_score": score,
                "sentiment_label": ts.get("ticker_sentiment_label", ""),
                "relevance_score": relevance,
            }
            ticker_articles.setdefault(ticker, []).append(
                (score, relevance, info))

    # Aggregate per ticker
    result = {}
    for ticker, articles in ticker_articles.items():
        scores = [s for s, r, _ in articles]
        relevances = [r for _, r, _ in articles]

        # Relevance-weighted average sentiment
        total_rel = sum(relevances)
        if total_rel > 0:
            avg_sent = sum(s * r for s, r, _ in articles) / total_rel
        else:
            avg_sent = statistics.mean(scores) if scores else 0.0

        avg_rel = statistics.mean(relevances) if relevances else 0.0

        bullish = sum(1 for s in scores if s >= 0.15)
        bearish = sum(1 for s in scores if s <= -0.15)
        neutral = len(scores) - bullish - bearish

        # Top articles by relevance
        sorted_articles = sorted(articles, key=lambda x: x[1], reverse=True)
        top = [info for _, _, info in sorted_articles[:MAX_ARTICLES_PER_SYMBOL]]

        result[ticker] = {
            "article_count": len(articles),
            "avg_sentiment": round(avg_sent, 4),
            "sentiment_label": classify_sentiment(avg_sent),
            "avg_relevance": round(avg_rel, 4),
            "bullish_count": bullish,
            "bearish_count": bearish,
            "neutral_count": neutral,
            "top_articles": top,
        }

    return result


def build_forex_pair_sentiments(ticker_sentiments, watchlist):
    """Combine base/quote currency sentiments for each forex pair.

    e.g. EURUSD = FOREX:EUR sentiment - FOREX:USD sentiment
    """
    pairs = {}
    for asset in watchlist.get("forex", []):
        symbol = asset["symbol"]
        base_key = f"FOREX:{asset['from']}"
        quote_key = f"FOREX:{asset['to']}"

        base_data = ticker_sentiments.get(base_key)
        quote_data = ticker_sentiments.get(quote_key)

        base_sent = base_data["avg_sentiment"] if base_data else None
        quote_sent = quote_data["avg_sentiment"] if quote_data else None

        if base_sent is not None and quote_sent is not None:
            net = round(base_sent - quote_sent, 4)
        else:
            net = None

        pairs[symbol] = {
            "base_currency": asset["from"],
            "quote_currency": asset["to"],
            "base_sentiment": base_sent,
            "quote_sentiment": quote_sent,
            "net_sentiment": net,
            "net_label": classify_sentiment(net),
        }

    return pairs


def build_market_summary(ticker_sentiments):
    """Compute overall market summary from per-ticker sentiments."""
    if not ticker_sentiments:
        return {
            "total_articles": 0,
            "overall_sentiment": 0.0,
            "overall_label": "No Data",
            "most_bullish": None,
            "most_bearish": None,
        }

    total_articles = sum(
        t["article_count"] for t in ticker_sentiments.values())
    scores = [t["avg_sentiment"] for t in ticker_sentiments.values()
              if t["article_count"] > 0]
    overall = statistics.mean(scores) if scores else 0.0

    # Most bullish/bearish (by avg sentiment, minimum 2 articles)
    qualified = {k: v for k, v in ticker_sentiments.items()
                 if v["article_count"] >= 2}
    most_bullish = max(qualified, key=lambda k: qualified[k]["avg_sentiment"],
                       default=None) if qualified else None
    most_bearish = min(qualified, key=lambda k: qualified[k]["avg_sentiment"],
                       default=None) if qualified else None

    return {
        "total_articles": total_articles,
        "overall_sentiment": round(overall, 4),
        "overall_label": classify_sentiment(overall),
        "most_bullish": most_bullish,
        "most_bearish": most_bearish,
    }


# -- Persistence ------------------------------------------------------

def save_sentiment(date_str, data):
    """Atomic JSON write to news directory."""
    path = os.path.join(NEWS_DIR, f"sentiment-{date_str}.json")
    atomic_json_write(path, data)
    return path


def load_sentiment(date_str):
    """Load previously saved sentiment data. Returns dict or None."""
    path = os.path.join(NEWS_DIR, f"sentiment-{date_str}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


# -- Markdown rendering -----------------------------------------------

def format_markdown_section(data):
    """Render sentiment data as markdown lines for daily analysis."""
    lines = ["## News Sentiment", ""]

    symbols = data.get("symbols", {})
    if symbols:
        # Filter to symbols with articles, sort by sentiment
        active = {k: v for k, v in symbols.items() if v["article_count"] > 0}
        if active:
            lines.append(
                "| Symbol | Articles | Sentiment | Label |")
            lines.append(
                "|--------|----------|-----------|-------|")
            for sym in sorted(active, key=lambda s: active[s]["avg_sentiment"],
                              reverse=True):
                s = active[sym]
                lines.append(
                    f"| {sym} | {s['article_count']} | "
                    f"{s['avg_sentiment']:+.3f} | {s['sentiment_label']} |")
            lines.append("")

    forex_pairs = data.get("forex_pairs", {})
    if forex_pairs:
        has_data = any(v["net_sentiment"] is not None
                       for v in forex_pairs.values())
        if has_data:
            lines.append("**Forex pairs:**")
            lines.append("")
            lines.append(
                "| Pair | Base | Quote | Net | Label |")
            lines.append(
                "|------|------|-------|-----|-------|")
            for pair, v in sorted(forex_pairs.items()):
                if v["net_sentiment"] is not None:
                    lines.append(
                        f"| {pair} | {v['base_sentiment']:+.3f} | "
                        f"{v['quote_sentiment']:+.3f} | "
                        f"{v['net_sentiment']:+.3f} | {v['net_label']} |")
            lines.append("")

    summary = data.get("market_summary", {})
    if summary.get("total_articles", 0) > 0:
        parts = [
            f"**Market overall:** {summary['overall_label']} "
            f"({summary['overall_sentiment']:+.3f})",
            f"{summary['total_articles']} articles",
        ]
        if summary.get("most_bullish"):
            parts.append(f"Most bullish: {summary['most_bullish']}")
        if summary.get("most_bearish"):
            parts.append(f"Most bearish: {summary['most_bearish']}")
        lines.append(" | ".join(parts))
        lines.append("")

    return lines


# -- Main -------------------------------------------------------------

def main():
    today = date.today().isoformat()

    # Duplicate protection
    existing = load_sentiment(today)
    if existing:
        print(f"Sentiment data already collected for {today}")
        summary = existing.get("market_summary", {})
        print(f"  {summary.get('total_articles', 0)} articles, "
              f"overall: {summary.get('overall_label', '?')}")
        return

    if API_KEY == "demo":
        print("WARNING: Using demo API key — results may be limited",
              file=sys.stderr)

    watchlist = load_watchlist()
    batches = build_ticker_batches(watchlist)

    print(f"Fetching news sentiment for {today} "
          f"({sum(len(b) for b in batches)} tickers in {len(batches)} calls)")

    # Fetch all batches
    all_sentiments = {}
    api_calls = 0

    for i, batch in enumerate(batches):
        if api_calls > 0:
            print(f"  (rate limit pause before batch {i + 1}...)")
            time.sleep(65)

        tickers_str = ", ".join(batch[:5])
        if len(batch) > 5:
            tickers_str += f"... ({len(batch)} total)"
        print(f"  Batch {i + 1}/{len(batches)}: {tickers_str}")

        try:
            raw = fetch_news_batch(batch)
            api_calls += 1

            # Check for AV error responses
            if "Information" in raw or "Note" in raw:
                msg = raw.get("Information") or raw.get("Note")
                print(f"  WARNING: {msg}", file=sys.stderr)
                continue

            batch_sentiments = extract_ticker_sentiments(raw)
            all_sentiments.update(batch_sentiments)

            article_count = sum(
                v["article_count"] for v in batch_sentiments.values())
            print(f"    {len(batch_sentiments)} tickers, "
                  f"{article_count} articles")

        except Exception as e:
            err_str = str(e)
            if "call frequency" in err_str.lower():
                print(f"  RATE LIMITED — stopping", file=sys.stderr)
                break
            print(f"  ERROR: {e}", file=sys.stderr)

    # Build aggregates
    forex_pairs = build_forex_pair_sentiments(all_sentiments, watchlist)
    market_summary = build_market_summary(all_sentiments)

    data = {
        "date": today,
        "source": "alpha_vantage",
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
        "api_calls_used": api_calls,
        "symbols": all_sentiments,
        "forex_pairs": forex_pairs,
        "market_summary": market_summary,
    }

    path = save_sentiment(today, data)
    print(f"\nSaved to {path}")
    print(f"  {market_summary['total_articles']} articles across "
          f"{len(all_sentiments)} tickers")
    print(f"  Overall: {market_summary['overall_label']} "
          f"({market_summary['overall_sentiment']:+.3f})")
    if market_summary.get("most_bullish"):
        bull = all_sentiments.get(market_summary["most_bullish"], {})
        print(f"  Most bullish: {market_summary['most_bullish']} "
              f"({bull.get('avg_sentiment', 0):+.3f})")
    if market_summary.get("most_bearish"):
        bear = all_sentiments.get(market_summary["most_bearish"], {})
        print(f"  Most bearish: {market_summary['most_bearish']} "
              f"({bear.get('avg_sentiment', 0):+.3f})")


if __name__ == "__main__":
    main()
