#!/usr/bin/env python3
"""Fetch daily candles for all watchlist assets.

All asset classes use Yahoo Finance (free, no API key, no rate limit).
Alpha Vantage fetchers are retained for --full historical mode fallback.

Reads watchlist from config, saves structured JSON per asset.
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trading_common import (
    load_watchlist, av_fetch as fetch_url, av_extract_error,
    is_av_rate_limited, atomic_json_write, retry_fetch,
    validate_candles,
    AV_API_KEY, AV_CALLS_PER_MINUTE as CALLS_PER_MINUTE,
    DATA_DIR, CONFIG_DIR,
)


def fetch_forex(asset, outputsize="compact"):
    """Fetch forex daily candles."""
    raw = fetch_url({
        "function": "FX_DAILY",
        "from_symbol": asset["from"],
        "to_symbol": asset["to"],
        "outputsize": outputsize,
    })
    ts = raw.get("Time Series FX (Daily)", {})
    if not ts:
        raise RuntimeError(av_extract_error(raw) or "No data")
    return [
        {"date": d, "o": float(v["1. open"]), "h": float(v["2. high"]),
         "l": float(v["3. low"]), "c": float(v["4. close"])}
        for d, v in sorted(ts.items())
    ]


def fetch_stock(asset, outputsize="compact"):
    """Fetch stock daily candles."""
    raw = fetch_url({
        "function": "TIME_SERIES_DAILY",
        "symbol": asset["symbol"],
        "outputsize": outputsize,
    })
    ts = raw.get("Time Series (Daily)", {})
    if not ts:
        raise RuntimeError(av_extract_error(raw) or "No data")
    return [
        {"date": d, "o": float(v["1. open"]), "h": float(v["2. high"]),
         "l": float(v["3. low"]), "c": float(v["4. close"]),
         "v": int(v["5. volume"])}
        for d, v in sorted(ts.items())
    ]


def fetch_crypto(asset, outputsize="compact"):
    """Fetch crypto daily candles (Alpha Vantage returns full history regardless)."""
    raw = fetch_url({
        "function": "DIGITAL_CURRENCY_DAILY",
        "symbol": asset["symbol"],
        "market": asset.get("market", "USD"),
    })
    ts = raw.get("Time Series (Digital Currency Daily)", {})
    if not ts:
        raise RuntimeError(av_extract_error(raw) or "No data")
    return [
        {"date": d, "o": float(v["1. open"]), "h": float(v["2. high"]),
         "l": float(v["3. low"]), "c": float(v["4. close"]),
         "v": float(v.get("5. volume", "0"))}
        for d, v in sorted(ts.items())
    ]


def fetch_stock_yahoo(asset, compact=False):
    """Fetch stock daily candles from Yahoo Finance (free, no API key).

    compact=True: last ~200 days (daily cron pulls).
    compact=False: full history (backtest historical pulls).
    """
    symbol = asset["symbol"]
    period2 = int(time.time())
    period1 = period2 - (200 * 86400) if compact else 0  # now
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={period1}&period2={period2}&interval=1d"
           f"&includeAdjustedClose=true")
    raw = json.loads(retry_fetch(url, headers={"User-Agent": "Mozilla/5.0"}))

    chart = raw.get("chart", {}).get("result", [{}])[0]
    timestamps = chart.get("timestamp", [])
    quotes = chart.get("indicators", {}).get("quote", [{}])[0]
    opens = quotes.get("open", [])
    highs = quotes.get("high", [])
    lows = quotes.get("low", [])
    closes = quotes.get("close", [])
    volumes = quotes.get("volume", [])

    if not timestamps:
        raise RuntimeError("No data from Yahoo Finance")

    candles = []
    for i, ts in enumerate(timestamps):
        o = opens[i] if i < len(opens) else None
        h = highs[i] if i < len(highs) else None
        l = lows[i] if i < len(lows) else None
        c = closes[i] if i < len(closes) else None
        v = volumes[i] if i < len(volumes) else 0
        if any(x is None for x in (o, h, l, c)):
            continue
        d = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        candles.append({"date": d, "o": round(o, 4), "h": round(h, 4),
                        "l": round(l, 4), "c": round(c, 4), "v": int(v or 0)})
    return candles


def fetch_forex_yahoo(asset, compact=False):
    """Fetch forex daily candles from Yahoo Finance (free, no API key).

    Yahoo forex tickers use the format {FROM}{TO}=X (e.g. EURUSD=X).
    """
    yahoo_symbol = f"{asset['from']}{asset['to']}=X"
    period2 = int(time.time())
    period1 = period2 - (200 * 86400) if compact else 0
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}"
           f"?period1={period1}&period2={period2}&interval=1d")
    raw = json.loads(retry_fetch(url, headers={"User-Agent": "Mozilla/5.0"}))

    chart = raw.get("chart", {}).get("result", [{}])[0]
    timestamps = chart.get("timestamp", [])
    quotes = chart.get("indicators", {}).get("quote", [{}])[0]
    opens = quotes.get("open", [])
    highs = quotes.get("high", [])
    lows = quotes.get("low", [])
    closes = quotes.get("close", [])

    if not timestamps:
        raise RuntimeError(f"No forex data from Yahoo Finance for {yahoo_symbol}")

    candles = []
    for i, ts in enumerate(timestamps):
        o = opens[i] if i < len(opens) else None
        h = highs[i] if i < len(highs) else None
        l = lows[i] if i < len(lows) else None
        c = closes[i] if i < len(closes) else None
        if any(x is None for x in (o, h, l, c)):
            continue
        d = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        candles.append({"date": d, "o": round(o, 4), "h": round(h, 4),
                        "l": round(l, 4), "c": round(c, 4)})
    return candles


def fetch_crypto_yahoo(asset, compact=False):
    """Fetch crypto daily candles from Yahoo Finance (free, no API key).

    Yahoo crypto tickers use the format {SYMBOL}-{MARKET} (e.g. BTC-USD).
    """
    yahoo_symbol = f"{asset['symbol']}-{asset.get('market', 'USD')}"
    period2 = int(time.time())
    period1 = period2 - (200 * 86400) if compact else 0
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}"
           f"?period1={period1}&period2={period2}&interval=1d")
    raw = json.loads(retry_fetch(url, headers={"User-Agent": "Mozilla/5.0"}))

    chart = raw.get("chart", {}).get("result", [{}])[0]
    timestamps = chart.get("timestamp", [])
    quotes = chart.get("indicators", {}).get("quote", [{}])[0]
    opens = quotes.get("open", [])
    highs = quotes.get("high", [])
    lows = quotes.get("low", [])
    closes = quotes.get("close", [])
    volumes = quotes.get("volume", [])

    if not timestamps:
        raise RuntimeError(f"No crypto data from Yahoo Finance for {yahoo_symbol}")

    candles = []
    for i, ts in enumerate(timestamps):
        o = opens[i] if i < len(opens) else None
        h = highs[i] if i < len(highs) else None
        l = lows[i] if i < len(lows) else None
        c = closes[i] if i < len(closes) else None
        v = volumes[i] if i < len(volumes) else 0
        if any(x is None for x in (o, h, l, c)):
            continue
        d = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        candles.append({"date": d, "o": round(o, 4), "h": round(h, 4),
                        "l": round(l, 4), "c": round(c, 4),
                        "v": int(v or 0)})
    return candles


# AV fetchers retained for --full historical mode fallback only.
# Daily pulls use Yahoo Finance (uses_yahoo=True always).
FETCHERS = {
    "forex": fetch_forex,
    "stocks": fetch_stock,
    "crypto": fetch_crypto,
}


def save_candles(asset_class, symbol, candles, base_dir=None, source="alpha_vantage"):
    """Save candle data to JSON. Validates candles before saving."""
    candles = validate_candles(candles, symbol=symbol)
    # Guard: refuse to overwrite existing data with an empty response
    out_dir = os.path.join(base_dir or DATA_DIR, asset_class)
    path = os.path.join(out_dir, f"{symbol}-daily.json")
    if not candles and os.path.exists(path):
        raise RuntimeError(
            f"Refusing to overwrite {symbol} with empty candle list"
        )
    out = {
        "symbol": symbol,
        "asset_class": asset_class,
        "interval": "daily",
        "source": source,
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
        "candles": candles,
    }
    atomic_json_write(path, out)
    return path


from trading_common import HISTORICAL_DIR
MIN_HISTORICAL_CANDLES = 500  # skip re-download if file has this many


def _historical_exists(asset_class, symbol):
    """Check if a historical file already exists with enough data."""
    path = os.path.join(HISTORICAL_DIR, asset_class, f"{symbol}-daily.json")
    if not os.path.exists(path):
        return False, 0
    try:
        with open(path) as f:
            data = json.load(f)
        count = len(data.get("candles", []))
        return count >= MIN_HISTORICAL_CANDLES, count
    except (json.JSONDecodeError, KeyError):
        return False, 0


def main():
    full_mode = "--full" in sys.argv
    skip_crypto = "--skip-crypto" in sys.argv

    if AV_API_KEY is None:
        print("WARNING: ALPHA_VANTAGE_API_KEY not set — forex/crypto will be skipped",
              file=sys.stderr)

    outputsize = "full" if full_mode else "compact"
    save_dir = HISTORICAL_DIR if full_mode else None

    if full_mode:
        print(f"FULL HISTORY MODE — outputsize={outputsize}, saving to {HISTORICAL_DIR}/")
        print(f"  (resumable — skips symbols with >= {MIN_HISTORICAL_CANDLES} candles)")

    try:
        watchlist = load_watchlist()
    except FileNotFoundError:
        print(f"ERROR: watchlist.json not found at {CONFIG_DIR}/watchlist.json", file=sys.stderr)
        sys.exit(1)
    total = 0
    errors = 0
    skipped = 0
    call_count = 0  # track API calls for rate limiting
    rate_limited = False

    # Build flat list of (asset_class, asset, fetcher)
    jobs = []
    for asset_class in ["forex", "stocks", "crypto"]:
        if skip_crypto and asset_class == "crypto":
            print("Skipping crypto (--skip-crypto)")
            continue
        fetcher = FETCHERS[asset_class]
        for asset in watchlist.get(asset_class, []):
            jobs.append((asset_class, asset, fetcher))

    for idx, (asset_class, asset, fetcher) in enumerate(jobs):
        symbol = asset["symbol"]
        uses_yahoo = True  # all asset classes use Yahoo Finance for daily pulls

        # In full mode, skip symbols we already have
        if full_mode:
            exists, count = _historical_exists(asset_class, symbol)
            if exists:
                print(f"{asset_class:6s} {symbol:6s}: SKIP (already have {count} candles)")
                skipped += 1
                continue

        # Skip AV assets if no API key is configured
        if AV_API_KEY is None and not uses_yahoo:
            print(f"{asset_class:6s} {symbol:6s}: SKIP (no AV API key)")
            skipped += 1
            continue

        # Stop early if we hit the AV daily quota (stocks bypass this)
        if rate_limited and not uses_yahoo:
            print(f"{asset_class:6s} {symbol:6s}: SKIP (API quota exhausted — re-run later)")
            skipped += 1
            continue

        # Rate limit only applies to Alpha Vantage calls (forex + crypto)
        if not uses_yahoo:
            if call_count > 0 and call_count % CALLS_PER_MINUTE == 0:
                remaining = sum(1 for ac, a, _ in jobs[idx:]
                               if ac != "stocks"
                               and not (full_mode and _historical_exists(ac, a["symbol"])[0]))
                print(f"  (AV rate limit pause — ~{remaining} forex/crypto remaining)")
                time.sleep(65)
            elif call_count > 0:
                time.sleep(0.3)

        try:
            if uses_yahoo:
                if asset_class == "forex":
                    candles = fetch_forex_yahoo(asset, compact=(not full_mode))
                elif asset_class == "crypto":
                    candles = fetch_crypto_yahoo(asset, compact=(not full_mode))
                else:
                    candles = fetch_stock_yahoo(asset, compact=(not full_mode))
                source = "yahoo_finance"
            else:
                candles = fetcher(asset, outputsize=outputsize)
                source = "alpha_vantage"
            save_candles(asset_class, symbol, candles, base_dir=save_dir,
                         source=source)
            latest = candles[-1] if candles else {}
            close_val = latest.get("c", "?")
            close_str = f"{close_val:.5f}" if isinstance(close_val, (int, float)) else str(close_val)
            count_str = f" ({len(candles)} candles)" if full_mode else ""
            print(f"{asset_class:6s} {symbol:6s}: close={close_str:>12s} ({latest.get('date', '?')}){count_str}")
            total += 1
        except Exception as e:
            err_str = str(e)
            if is_av_rate_limited(err_str):
                print(f"{asset_class:6s} {symbol:6s}: RATE LIMITED — stopping AV calls", file=sys.stderr)
                rate_limited = True
                errors += 1
            else:
                print(f"{asset_class:6s} {symbol:6s}: ERROR {e}", file=sys.stderr)
                errors += 1
        if not uses_yahoo:
            call_count += 1

    parts = [f"Fetched {total}/{total + errors + skipped} assets"]
    if skipped:
        parts.append(f"{skipped} skipped")
    if errors:
        parts.append(f"{errors} errors")
    if rate_limited:
        parts.append("re-run to fetch remaining")
    print(f"\n{' | '.join(parts)}")


if __name__ == "__main__":
    main()
