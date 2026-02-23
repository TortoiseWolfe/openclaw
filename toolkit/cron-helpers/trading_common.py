#!/usr/bin/env python3
"""Shared functions for the trading pipeline.

Centralizes path constants, watchlist loading, candle loading,
signal classification, AV API helpers, and atomic file I/O
used across market_data_pull, market_trade_decision,
market_post_mortem, market_news_sentiment, and
market_news_supplementary.
"""

import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import date as _date_type, datetime, timedelta, timezone
from urllib.parse import urlencode

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except ImportError:
    ET = timezone(timedelta(hours=-5))

# ── Path constants (inside Docker container) ────────────────────────

BASE_DIR = os.environ.get("TRADING_BASE_DIR", "/home/node/repos/Trading")
CONFIG_DIR = os.path.join(BASE_DIR, "config")
DATA_DIR = os.path.join(BASE_DIR, "data")
PRIVATE_DIR = os.path.join(BASE_DIR, "private")
NEWS_DIR = os.path.join(DATA_DIR, "news")
HISTORICAL_DIR = os.path.join(DATA_DIR, "historical")
STATE_FILE = os.path.join(PRIVATE_DIR, "paper-state.json")
LESSONS_FILE = os.path.join(PRIVATE_DIR, "trade-lessons.json")
PAPER_MD = os.path.join(PRIVATE_DIR, "paper-trades.md")
JOURNAL = os.path.join(PRIVATE_DIR, "trade-journal.md")
EDU_DIR = os.path.join(BASE_DIR, "education")
CURRICULUM = os.path.join(EDU_DIR, "curriculum-progress.md")

# ── Candle validation ──────────────────────────────────────────────

def validate_candle(candle):
    """Validate a single candle dict. Returns (ok, reason).

    Checks: all OHLC > 0, h >= max(o,c), l <= min(o,c).
    """
    o = candle.get("o", 0)
    h = candle.get("h", 0)
    l = candle.get("l", 0)
    c = candle.get("c", 0)
    if any(v <= 0 for v in (o, h, l, c)):
        return False, "zero/negative OHLC"
    if h < max(o, c):
        return False, f"high {h} < max(open {o}, close {c})"
    if l > min(o, c):
        return False, f"low {l} > min(open {o}, close {c})"
    return True, None


def validate_candles(candles, symbol="?"):
    """Validate a list of candles, logging warnings. Returns valid candles only."""
    valid = []
    bad = 0
    for c in candles:
        ok, reason = validate_candle(c)
        if ok:
            valid.append(c)
        else:
            bad += 1
    if bad > 0:
        print(f"WARNING: {symbol} — {bad} invalid candles filtered at ingestion",
              file=sys.stderr)
    return valid


# ── Alpha Vantage config ────────────────────────────────────────────

AV_API_KEY = os.environ.get("ALPHA_VANTAGE_API_KEY") or None
AV_CALLS_PER_MINUTE = int(os.environ.get("AV_CALLS_PER_MINUTE", "5"))
AV_BASE_URL = "https://www.alphavantage.co/query"


# ── Watchlist ───────────────────────────────────────────────────────

def load_watchlist():
    """Load watchlist.json from the config directory."""
    path = os.path.join(CONFIG_DIR, "watchlist.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── Candle loading ──────────────────────────────────────────────────

def load_candles(asset_class, symbol, warn_stale_days=0, max_stale_days=0,
                 today=None):
    """Load daily candle data for a symbol.

    Returns list of {date, o, h, l, c}. Expects new-schema
    (numeric values, "o"/"h"/"l"/"c" keys).

    Args:
        asset_class: "forex", "stocks", or "crypto"
        symbol: e.g. "EURUSD", "AAPL", "BTC"
        warn_stale_days: if > 0, print warning when latest candle
            is older than this many days. Pass 0 to disable.
        max_stale_days: if > 0, return [] when latest candle is older
            than this many days (blocks trading on stale data).
        today: date object for staleness check (defaults to date.today())

    Raises FileNotFoundError if the data file doesn't exist.
    """
    path = os.path.join(DATA_DIR, asset_class, f"{symbol}-daily.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    result = []
    invalid_count = 0
    for c in data.get("candles", []):
        o = float(c.get("o", 0))
        h = float(c.get("h", 0))
        l = float(c.get("l", 0))
        cl = float(c.get("c", 0))
        if any(v <= 0 for v in (o, h, l, cl)):
            invalid_count += 1
            continue
        result.append({"date": c["date"], "o": o, "h": h, "l": l, "c": cl})
    if invalid_count > 0:
        print(f"WARNING: {symbol} — {invalid_count} candles filtered "
              f"(zero/negative values)", file=sys.stderr)
    if result:
        ref = today or _date_type.today()
        latest = _date_type.fromisoformat(result[-1]["date"])
        age_days = (ref - latest).days
        if max_stale_days > 0 and age_days > max_stale_days:
            print(f"STALE: {symbol} data is {age_days} days old — skipping "
                  f"(limit: {max_stale_days}d)", file=sys.stderr)
            return []
        if warn_stale_days > 0 and age_days > warn_stale_days:
            print(f"WARNING: {symbol} data is {age_days} days old "
                  f"(latest: {result[-1]['date']})", file=sys.stderr)
    return result


def load_candles_safe(asset_class, symbol):
    """Load candles, returning [] on FileNotFoundError."""
    try:
        return load_candles(asset_class, symbol)
    except FileNotFoundError:
        return []


# ── Signal classification ───────────────────────────────────────────

def classify_signal(reason):
    """Classify a trade reason into signal type for lessons tracking.

    Parses the first component of the comma-separated reason string
    from market_trade_decision.py's analyze() function.
    """
    r = reason.lower()
    if r.startswith("uptrend") or r.startswith("downtrend"):
        return "trend"
    if r.startswith("sma"):
        return "sma"
    if r.startswith("ranging +"):
        return "pattern"
    if "near support" in r or "near resistance" in r:
        return "range_position"
    if "yolo" in r or "last candle" in r:
        return "yolo"
    return "unknown"


# ── Alpha Vantage API ───────────────────────────────────────────────

RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}


def retry_fetch(url, max_retries=3, backoff=2, timeout=30, headers=None):
    """Fetch URL with exponential backoff on transient errors.

    Retries on URLError, TimeoutError, ConnectionError, and HTTP 429/5xx.
    Returns the raw response bytes.
    """
    req = urllib.request.Request(url)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    last_err = None
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code in RETRYABLE_HTTP_CODES and attempt < max_retries - 1:
                delay = backoff * (2 ** attempt)
                print(f"  Retry {attempt + 1}/{max_retries} in {delay}s: HTTP {e.code}",
                      file=sys.stderr)
                time.sleep(delay)
                last_err = e
            else:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = e
            if attempt < max_retries - 1:
                delay = backoff * (2 ** attempt)
                print(f"  Retry {attempt + 1}/{max_retries} in {delay}s: {e}",
                      file=sys.stderr)
                time.sleep(delay)
    raise last_err


def av_fetch(params):
    """Fetch from Alpha Vantage with given query params.

    Automatically appends the API key. Returns parsed JSON dict.
    Raises RuntimeError if no API key is configured.
    """
    if AV_API_KEY is None:
        raise RuntimeError("ALPHA_VANTAGE_API_KEY not set — cannot fetch AV data")
    params["apikey"] = AV_API_KEY
    url = f"{AV_BASE_URL}?{urlencode(params)}"
    data = retry_fetch(url)
    return json.loads(data)


def av_extract_error(raw):
    """Extract error message from an AV response, or None if no error."""
    return raw.get("Note") or raw.get("Information") or raw.get("Error Message")


def is_av_rate_limited(error_msg):
    """Check if an AV error message indicates rate limiting or quota."""
    if not error_msg:
        return False
    msg = error_msg.lower()
    return ("call frequency" in msg or "premium" in msg
            or "rate limit" in msg or "25 requests" in msg)


# ── Atomic file I/O ─────────────────────────────────────────────────

def atomic_json_write(path, data, indent=2):
    """Write JSON data atomically via tmp file + os.replace."""
    dir_ = os.path.dirname(path)
    os.makedirs(dir_, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass
        raise


def atomic_text_write(path, text):
    """Write text data atomically via tmp file + os.replace."""
    dir_ = os.path.dirname(path)
    os.makedirs(dir_, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass
        raise


# ── Correlation guard ─────────────────────────────────────────────

def _lookup_asset_config(watchlist, asset_class, symbol):
    """Find the config dict for a symbol in the watchlist."""
    for asset in watchlist.get(asset_class, []):
        if asset["symbol"] == symbol:
            return asset
    return {"symbol": symbol}


def check_correlation_guard(asset_class, symbol, direction, config,
                            open_positions, rules, watchlist):
    """Check if opening this position would create excess correlation.

    Returns (allowed, reason).

    Forex: decomposes each pair into currency exposures. EURUSD LONG = long EUR,
    short USD. Blocks if any single currency+side exceeds forex_max_same_currency.

    Stocks: groups by sector. Blocks if same group count >= stock_max_same_group.

    Crypto: always allowed (already capped at 1 position).
    """
    corr_cfg = rules.get("correlation", {})
    if not corr_cfg.get("enabled", False):
        return (True, "disabled")

    if asset_class == "crypto":
        return (True, "ok")

    if asset_class == "forex":
        max_same = corr_cfg.get("forex_max_same_currency", 1)

        # Build exposure map from open forex positions: {(currency, side): count}
        exposure = {}
        for pos in open_positions:
            if pos["asset_class"] != "forex":
                continue
            pos_cfg = _lookup_asset_config(watchlist, "forex", pos["symbol"])
            base = pos_cfg.get("from", pos["symbol"][:3])
            quote = pos_cfg.get("to", pos["symbol"][3:])
            d = pos["direction"]
            # LONG pair = long base, short quote
            # SHORT pair = short base, long quote
            if d == "LONG":
                exposure[(base, "long")] = exposure.get((base, "long"), 0) + 1
                exposure[(quote, "short")] = exposure.get((quote, "short"), 0) + 1
            else:
                exposure[(base, "short")] = exposure.get((base, "short"), 0) + 1
                exposure[(quote, "long")] = exposure.get((quote, "long"), 0) + 1

        # Compute proposed exposure
        base = config.get("from", symbol[:3])
        quote = config.get("to", symbol[3:])
        if direction == "LONG":
            proposed = [(base, "long"), (quote, "short")]
        else:
            proposed = [(base, "short"), (quote, "long")]

        for ccy, side in proposed:
            current = exposure.get((ccy, side), 0)
            if current >= max_same:
                return (False, f"{side} {ccy} ({current + 1} > {max_same})")

        return (True, "ok")

    if asset_class == "stocks":
        max_same = corr_cfg.get("stock_max_same_group", 1)
        group = config.get("group")
        if not group:
            return (True, "no_group")

        count = 0
        for pos in open_positions:
            if pos["asset_class"] != "stocks":
                continue
            pos_cfg = _lookup_asset_config(watchlist, "stocks", pos["symbol"])
            if pos_cfg.get("group") == group:
                count += 1

        if count >= max_same:
            return (False, f"{group} ({count + 1} > {max_same})")

        return (True, "ok")

    return (True, "ok")


# ── Sentiment loading (for trade decisions) ──────────────────────

def load_sentiment_for_trading(today_str=None):
    """Load today's sentiment scores for trading decisions.

    Returns {symbol: score} where score is float (-1.0 to +1.0).
    Forex pairs use net sentiment (base - quote currency).
    Stocks/crypto use direct ticker sentiment.
    Returns empty dict on missing data or errors.
    """
    if today_str is None:
        today_str = datetime.now(ET).strftime("%Y-%m-%d")

    path = os.path.join(NEWS_DIR, f"sentiment-{today_str}.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    scores = {}

    # Forex pairs: use net sentiment (base - quote)
    for pair, info in data.get("forex_pairs", {}).items():
        net = info.get("net_sentiment")
        if net is not None:
            scores[pair] = net

    # Stocks and crypto from per-ticker data
    for ticker, info in data.get("symbols", {}).items():
        score = info.get("avg_sentiment")
        if score is None or info.get("article_count", 0) == 0:
            continue
        if ticker.startswith("CRYPTO:"):
            scores[ticker.replace("CRYPTO:", "")] = score
        elif not ticker.startswith("FOREX:"):
            scores[ticker] = score

    return scores
