#!/usr/bin/env python3
"""Supplementary Alpha Vantage data pull — maximises 25 daily calls.

Runs at 8:35 AM ET (after main data pull, before news sentiment).
market_data_pull uses Yahoo Finance (0 AV calls), sentiment uses 3,
leaving 22 calls/day for this script.

Daily plan (every weekday):
  7 FX_INTRADAY   — all 7 forex pairs (fresh intraday data)
  10 EARNINGS     — half the stocks (set A on odd days, set B on even)
  5 OVERVIEW      — rotating slice of 20 stocks (full cycle every 4 days)

Earnings data feeds into trade decision (skip stocks near earnings).
Company overviews provide fundamentals for future analysis.
Intraday forex gives better entry signals than daily-only.

Usage (from Docker):
  python3 market_data_supplement.py
  python3 market_data_supplement.py --dry-run   # show plan without fetching
"""

import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trading_common import (
    load_watchlist, av_fetch, av_extract_error, is_av_rate_limited,
    atomic_json_write, AV_API_KEY, AV_CALLS_PER_MINUTE, DATA_DIR, ET,
)

AV_DAILY_LIMIT = 25


def _sentiment_call_count(watchlist):
    """Estimate how many AV calls the sentiment script will use."""
    stocks = watchlist.get("stocks", [])
    crypto = watchlist.get("crypto", [])
    forex = watchlist.get("forex", [])
    forex_currencies = set()
    for a in forex:
        forex_currencies.add(a["from"])
        forex_currencies.add(a["to"])
    mid = len(stocks) // 2
    batches = [b for b in [
        stocks[:mid],
        list(stocks[mid:]) + list(crypto),
        sorted(forex_currencies),
    ] if b]
    return len(batches)
SUPPLEMENT_DIR = os.path.join(DATA_DIR, "supplement")


# ── Fetchers ────────────────────────────────────────────────────────

def fetch_earnings(symbol):
    """Fetch earnings calendar for a single stock symbol.

    Returns dict with next_earnings_date, recent earnings, EPS data.
    AV endpoint: EARNINGS (1 call per symbol).
    """
    raw = av_fetch({"function": "EARNINGS", "symbol": symbol})

    err = av_extract_error(raw)
    if err:
        raise RuntimeError(err)

    quarterly = raw.get("quarterlyEarnings", [])
    annual = raw.get("annualEarnings", [])

    # Next upcoming earnings: first entry with no reportedEPS
    upcoming = None
    for q in quarterly:
        if q.get("reportedEPS") in (None, "", "None"):
            upcoming = q.get("fiscalDateEnding")
            break

    # Most recent actual
    latest = None
    if quarterly:
        for q in quarterly:
            if q.get("reportedEPS") not in (None, "", "None"):
                latest = {
                    "date": q.get("fiscalDateEnding"),
                    "reported_date": q.get("reportedDate"),
                    "reported_eps": q.get("reportedEPS"),
                    "estimated_eps": q.get("estimatedEPS"),
                    "surprise": q.get("surprise"),
                    "surprise_pct": q.get("surprisePercentage"),
                }
                break

    return {
        "symbol": symbol,
        "next_earnings_date": upcoming,
        "latest_earnings": latest,
        "quarterly_count": len(quarterly),
        "annual_count": len(annual),
    }


def fetch_overview(symbol):
    """Fetch company overview/fundamentals for a single stock.

    AV endpoint: OVERVIEW (1 call per symbol).
    """
    raw = av_fetch({"function": "OVERVIEW", "symbol": symbol})

    err = av_extract_error(raw)
    if err:
        raise RuntimeError(err)

    # Extract key fields only — full response is huge
    return {
        "symbol": raw.get("Symbol", symbol),
        "name": raw.get("Name"),
        "sector": raw.get("Sector"),
        "industry": raw.get("Industry"),
        "market_cap": raw.get("MarketCapitalization"),
        "pe_ratio": raw.get("PERatio"),
        "forward_pe": raw.get("ForwardPE"),
        "eps": raw.get("EPS"),
        "dividend_yield": raw.get("DividendYield"),
        "52_week_high": raw.get("52WeekHigh"),
        "52_week_low": raw.get("52WeekLow"),
        "50_day_ma": raw.get("50DayMovingAverage"),
        "200_day_ma": raw.get("200DayMovingAverage"),
        "beta": raw.get("Beta"),
        "profit_margin": raw.get("ProfitMargin"),
        "revenue_growth_yoy": raw.get("QuarterlyRevenueGrowthYOY"),
        "analyst_target": raw.get("AnalystTargetPrice"),
        "analyst_rating": raw.get("AnalystRatingStrongBuy"),
    }


def fetch_forex_intraday(from_sym, to_sym, interval="60min"):
    """Fetch intraday forex candles.

    AV endpoint: FX_INTRADAY (1 call per pair).
    Returns list of candle dicts (most recent ~100 bars of 1h data).
    """
    raw = av_fetch({
        "function": "FX_INTRADAY",
        "from_symbol": from_sym,
        "to_symbol": to_sym,
        "interval": interval,
        "outputsize": "compact",
    })

    key = f"Time Series FX ({interval.replace('min', ' min')})"
    # AV uses various key formats — try a few
    ts = raw.get(key) or raw.get(f"Time Series FX (Intraday)") or {}
    if not ts:
        # Try to find the time series key dynamically
        for k in raw:
            if "Time Series" in k:
                ts = raw[k]
                break
    if not ts:
        raise RuntimeError(av_extract_error(raw) or "No intraday data")

    return [
        {
            "datetime": d,
            "o": float(v["1. open"]),
            "h": float(v["2. high"]),
            "l": float(v["3. low"]),
            "c": float(v["4. close"]),
        }
        for d, v in sorted(ts.items())
    ]


# ── Rotation schedule ───────────────────────────────────────────────

def build_rotation(watchlist, weekday):
    """Build the day's fetch plan — same structure every weekday.

    Returns list of (fetch_type, args_dict) tuples.
    Each fetch_type is 'earnings', 'overview', or 'forex_intraday'.
    Budget is computed dynamically: AV_DAILY_LIMIT - sentiment calls.
    """
    stocks = [a["symbol"] for a in watchlist.get("stocks", [])]
    forex = watchlist.get("forex", [])

    mid = len(stocks) // 2
    set_a = stocks[:mid]       # first 10
    set_b = stocks[mid:]       # last 10

    plan = []

    # 1) All forex pairs get intraday data every day (7 calls)
    for pair in forex:
        plan.append(("forex_intraday", {
            "from": pair["from"], "to": pair["to"],
            "symbol": pair["symbol"],
        }))

    # 2) Earnings: alternate halves (10 calls)
    #    Odd weekdays (Mon=0, Wed=2, Fri=4) → set A
    #    Even weekdays (Tue=1, Thu=3)       → set B
    earnings_set = set_a if weekday % 2 == 0 else set_b
    for s in earnings_set:
        plan.append(("earnings", {"symbol": s}))

    # 3) Overviews: rotate 5 stocks/day through all 20 (5 calls)
    #    weekday 0 → stocks[0:5], weekday 1 → stocks[5:10], etc.
    #    Full cycle every 4 weekdays.
    overview_start = (weekday % 4) * 5
    overview_slice = stocks[overview_start:overview_start + 5]
    for s in overview_slice:
        plan.append(("overview", {"symbol": s}))

    budget = AV_DAILY_LIMIT - _sentiment_call_count(watchlist)
    if len(plan) > budget:
        print(f"  WARNING: plan has {len(plan)} calls, trimming to {budget} "
              f"(AV limit {AV_DAILY_LIMIT} - {AV_DAILY_LIMIT - budget} sentiment)")
    return plan[:budget]


# ── Persistence ─────────────────────────────────────────────────────

def save_earnings(symbol, data):
    """Save earnings data for a stock symbol."""
    data["lastUpdated"] = datetime.now(timezone.utc).isoformat()
    path = os.path.join(DATA_DIR, "stocks", f"{symbol}-earnings.json")
    atomic_json_write(path, data)
    return path


def save_overview(symbol, data):
    """Save company overview for a stock symbol."""
    data["lastUpdated"] = datetime.now(timezone.utc).isoformat()
    path = os.path.join(DATA_DIR, "stocks", f"{symbol}-overview.json")
    atomic_json_write(path, data)
    return path


def save_forex_intraday(symbol, candles):
    """Save intraday forex candles."""
    data = {
        "symbol": symbol,
        "interval": "60min",
        "source": "alpha_vantage",
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
        "candles": candles,
    }
    path = os.path.join(DATA_DIR, "forex", f"{symbol}-intraday.json")
    atomic_json_write(path, data)
    return path


# ── Load helpers (for trade decision integration) ───────────────────

def load_earnings(symbol):
    """Load earnings data for a symbol. Returns dict or None."""
    path = os.path.join(DATA_DIR, "stocks", f"{symbol}-earnings.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def days_until_earnings(symbol, today=None):
    """Return days until next earnings, or None if unknown.

    Positive = earnings in the future. Negative = just reported.
    Returns None if no earnings data available.
    """
    data = load_earnings(symbol)
    if not data or not data.get("next_earnings_date"):
        return None
    try:
        if today is None:
            today = datetime.now(ET).date()
        earnings_date = date.fromisoformat(data["next_earnings_date"])
        return (earnings_date - today).days
    except (ValueError, TypeError):
        return None


# ── Main ────────────────────────────────────────────────────────────

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

def main():
    dry_run = "--dry-run" in sys.argv
    today = datetime.now(ET).date()
    weekday = today.weekday()

    if weekday > 4:
        print(f"Weekend ({DAY_NAMES[weekday]}) — no supplementary pull needed")
        return

    if AV_API_KEY is None:
        print("WARNING: ALPHA_VANTAGE_API_KEY not set — skipping supplement",
              file=sys.stderr)
        return

    watchlist = load_watchlist()
    plan = build_rotation(watchlist, weekday)

    print(f"Supplementary data pull — {DAY_NAMES[weekday]} {today.isoformat()}")
    print(f"  Plan: {len(plan)} calls (budget: {DAILY_BUDGET})")

    if dry_run:
        for i, (fetch_type, args) in enumerate(plan, 1):
            sym = args.get("symbol", f"{args.get('from', '?')}/{args.get('to', '?')}")
            print(f"  [{i}] {fetch_type}: {sym}")
        print("  (dry run — no API calls made)")
        return

    call_count = 0
    fetched = 0
    errors = 0
    rate_limited = False

    for fetch_type, args in plan:
        if rate_limited:
            sym = args.get("symbol", "?")
            print(f"  {fetch_type:16s} {sym:8s}: SKIP (rate limited)")
            continue

        # Rate limit: 5 calls/min
        if call_count > 0 and call_count % AV_CALLS_PER_MINUTE == 0:
            print(f"  (rate limit pause — {len(plan) - call_count} remaining)")
            time.sleep(65)
        elif call_count > 0:
            time.sleep(0.3)

        try:
            if fetch_type == "earnings":
                sym = args["symbol"]
                data = fetch_earnings(sym)
                save_earnings(sym, data)
                next_e = data.get("next_earnings_date", "?")
                print(f"  earnings         {sym:8s}: next={next_e}")

            elif fetch_type == "overview":
                sym = args["symbol"]
                data = fetch_overview(sym)
                save_overview(sym, data)
                pe = data.get("pe_ratio", "?")
                mc = data.get("market_cap", "?")
                print(f"  overview         {sym:8s}: P/E={pe} cap={mc}")

            elif fetch_type == "forex_intraday":
                sym = args["symbol"]
                candles = fetch_forex_intraday(args["from"], args["to"])
                save_forex_intraday(sym, candles)
                latest = candles[-1] if candles else {}
                print(f"  forex_intraday   {sym:8s}: "
                      f"{len(candles)} bars, latest={latest.get('c', '?')}")

            fetched += 1

        except Exception as e:
            sym = args.get("symbol", "?")
            err_str = str(e)
            if is_av_rate_limited(err_str):
                print(f"  {fetch_type:16s} {sym:8s}: RATE LIMITED", file=sys.stderr)
                rate_limited = True
                errors += 1
            else:
                print(f"  {fetch_type:16s} {sym:8s}: ERROR {e}", file=sys.stderr)
                errors += 1

        call_count += 1

    parts = [f"Supplementary: {fetched}/{len(plan)} fetched"]
    if errors:
        parts.append(f"{errors} errors")
    if rate_limited:
        parts.append("hit rate limit")
    print(f"\n{' | '.join(parts)}")


if __name__ == "__main__":
    main()
