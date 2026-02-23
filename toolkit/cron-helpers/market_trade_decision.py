#!/usr/bin/env python3
"""Unified multi-asset paper trading engine (orchestrator).

Reads candle data for forex, stocks, and crypto. Analyzes trends, manages
open/close trades across all asset classes. Single shared balance.

PHILOSOPHY: Aggressive learner. This is play money — we learn more from
losses than from sitting on cash. The education system (BabyPips) progressively
unlocks smarter analysis techniques. Early on we trade dumb and often.
As lessons are completed, the engine gets new tools.

State is kept in paper-state.json. Outputs paper-trades.md, daily analysis,
and trade journal entries.

Decomposed modules:
  - trading_handlers.py  — ForexHandler, StockHandler, CryptoHandler
  - trading_signals.py   — analyze(), compute_sma(), education loading
  - trading_output.py    — write_paper_md(), daily analysis, journal
"""

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trading_common import (
    load_watchlist, load_candles, classify_signal,
    load_sentiment_for_trading, check_correlation_guard,
    atomic_json_write,
    CONFIG_DIR, STATE_FILE, PAPER_MD, ET,
)
from trading_handlers import HANDLERS
from trading_signals import (
    LOOKBACK, load_education_progress, education_summary,
    load_lessons, analyze, compute_sma, compute_sentiment_multiplier,
)
from market_data_supplement import days_until_earnings

EARNINGS_BUFFER_DAYS = 2  # skip stock entries this close to earnings
from trading_output import (
    write_paper_md, write_daily_analysis, cleanup_old_analyses,
    append_journal,
)


# Re-export for backwards compatibility (backtest engine, tests)
from trading_handlers import ForexHandler, StockHandler, CryptoHandler


# ── Config & state ───────────────────────────────────────────────────

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
        # Ensure peak_balance exists (migration for older state files)
        if "peak_balance" not in state:
            state["peak_balance"] = max(state["balance"], 10000.0)
        return state
    return {"balance": 10000.0, "peak_balance": 10000.0,
            "next_id": 1, "open": [], "closed": []}


def save_state(state):
    atomic_json_write(STATE_FILE, state)


# ── Trade management ─────────────────────────────────────────────────

def check_stops(state, prices, today, rules=None, cross_rates=None):
    """Close positions that hit stop loss or take profit.

    Uses daily high/low (not just close) to detect intraday SL/TP hits,
    matching the backtest engine's behavior. Checks SL before TP
    (conservative: assume adverse move happened first).
    """
    still_open = []
    newly_closed = []

    for pos in state["open"]:
        ac = pos["asset_class"]
        sym = pos["symbol"]
        handler = HANDLERS[ac]
        price_data = prices.get((ac, sym))
        if price_data is None:
            still_open.append(pos)
            continue
        close, high, low = price_data

        hit_sl = hit_tp = False
        if pos["direction"] == "LONG":
            hit_sl = low <= pos["stop_loss"]
            hit_tp = high >= pos["take_profit"]
        else:
            hit_sl = high >= pos["stop_loss"]
            hit_tp = low <= pos["take_profit"]

        if hit_sl:
            exit_price = pos["stop_loss"]
            pnl = handler.calculate_pnl(
                pos["entry"], exit_price, pos["direction"], pos["size"],
                sym, _asset_config(ac, sym), rules=rules, cross_rates=cross_rates,
            )
            newly_closed.append({
                **pos,
                "date_closed": today,
                "exit": round(exit_price, 5),
                "pnl_dollars": pnl,
                "close_reason": "stop loss",
            })
        elif hit_tp:
            exit_price = pos["take_profit"]
            pnl = handler.calculate_pnl(
                pos["entry"], exit_price, pos["direction"], pos["size"],
                sym, _asset_config(ac, sym), rules=rules, cross_rates=cross_rates,
            )
            newly_closed.append({
                **pos,
                "date_closed": today,
                "exit": round(exit_price, 5),
                "pnl_dollars": pnl,
                "close_reason": "take profit",
            })
        else:
            pnl = handler.calculate_pnl(
                pos["entry"], close, pos["direction"], pos["size"],
                sym, _asset_config(ac, sym), rules=rules, cross_rates=cross_rates,
            )
            updated = {**pos, "current_price": close, "unrealized_pnl": pnl}
            still_open.append(updated)

    state["open"] = still_open
    state["closed"].extend(newly_closed)
    for c in newly_closed:
        state["balance"] += c["pnl_dollars"]
    if state["balance"] < 0:
        print(f"WARNING: Balance went negative (${state['balance']:,.2f}). "
              f"Flooring to $0 — no new trades until wins recover.", file=sys.stderr)
        state["balance"] = 0.0
    return newly_closed


def friday_close(state, prices, today, today_date, rules=None, cross_rates=None):
    """Close positions for asset classes with weekend close rule."""
    if today_date.weekday() != 4:
        return []
    if not state["open"]:
        return []
    closed = []
    keep = []

    for pos in state["open"]:
        ac = pos["asset_class"]
        handler = HANDLERS[ac]
        if not handler.weekend_close():
            keep.append(pos)
            continue

        sym = pos["symbol"]
        price_data = prices.get((ac, sym))
        exit_price = price_data[0] if price_data else pos["entry"]
        pnl = handler.calculate_pnl(
            pos["entry"], exit_price, pos["direction"], pos["size"],
            sym, _asset_config(ac, sym), rules=rules, cross_rates=cross_rates,
        )
        closed.append({
            **pos,
            "date_closed": today,
            "exit": round(exit_price, 5),
            "pnl_dollars": pnl,
            "close_reason": "weekend close",
        })

    state["closed"].extend(closed)
    state["open"] = keep
    for c in closed:
        state["balance"] += c["pnl_dollars"]
    if state["balance"] < 0:
        print(f"WARNING: Balance went negative (${state['balance']:,.2f}). "
              f"Flooring to $0 — no new trades until wins recover.", file=sys.stderr)
        state["balance"] = 0.0
    return closed


def _get_slippage(rules, asset_class, price):
    """Return absolute slippage amount for the asset class."""
    slip_cfg = rules.get("slippage", {})
    if asset_class == "crypto":
        return price * slip_cfg.get("crypto_pct", 0)
    return slip_cfg.get(asset_class, 0)


def open_trade(state, asset_class, symbol, signal, watchlist, today,
               lessons=None, sentiment_multiplier=1.0, regime=None,
               cross_rates=None):
    """Open a new paper trade."""
    handler = HANDLERS[asset_class]
    config = _asset_config(asset_class, symbol)
    rules = watchlist["rules"]

    # Apply slippage: adverse entry + widened stop for exit slippage
    slip = _get_slippage(rules, asset_class, signal["entry"])
    if signal["direction"] == "LONG":
        entry = signal["entry"] + slip    # buy at worse price
        stop_loss = signal["stop_loss"] - slip  # exit slippage on stop fill
    else:
        entry = signal["entry"] - slip    # sell at worse price
        stop_loss = signal["stop_loss"] + slip  # exit slippage on stop fill
    take_profit = signal["take_profit"]   # TP fills are limit orders — no slippage

    # Size using adjusted stop distance (accounts for slippage in risk calc)
    stop_distance = abs(entry - stop_loss)
    size = handler.position_size(
        state["balance"], rules["max_risk"],
        stop_distance, entry,
        symbol, config, cross_rates=cross_rates,
    )
    if size == 0:
        return None

    # Cap notional value at max_leverage × balance (prevents tiny-ATR blowups)
    max_leverage = rules.get("max_leverage", 5)
    notional = size * entry
    max_notional = state["balance"] * max_leverage
    if notional > max_notional and max_notional > 0:
        size = max(1, int(max_notional / entry))

    # Apply lessons-based confidence multiplier to position size
    if lessons and size > 0:
        sig_type = classify_signal(signal["reason"])
        sig_mult = lessons.get("by_signal_type", {}).get(sig_type, {}).get("confidence_multiplier", 1.0)
        cls_mult = lessons.get("by_asset_class", {}).get(asset_class, {}).get("confidence_multiplier", 1.0)
        combined = max(0.25, min(1.5, sig_mult * cls_mult))
        if combined != 1.0:
            size = max(1, round(size * combined))

    # Apply sentiment multiplier (0.0-1.0, never boosts)
    if sentiment_multiplier < 1.0 and size > 0:
        size = max(1, round(size * sentiment_multiplier))

    # Regime-based sizing: scale down in adverse regimes
    regime_sizing = rules.get("regime_sizing", {})
    if regime_sizing.get("enabled", False) and regime and size > 0:
        regime_mult = regime_sizing.get("multipliers", {}).get(regime, 1.0)
        if regime_mult <= 0:
            return None  # regime blocks entry entirely
        if regime_mult != 1.0:
            size = max(1, round(size * regime_mult))

    trade = {
        "id": f"T{state['next_id']:03d}",
        "date_opened": today,
        "asset_class": asset_class,
        "symbol": symbol,
        "direction": signal["direction"],
        "entry": round(entry, 5),
        "stop_loss": round(stop_loss, 5),
        "take_profit": round(take_profit, 5),
        "size": size,
        "reason": signal["reason"],
    }
    state["open"].append(trade)
    state["next_id"] += 1
    return trade


_watchlist_cache = None

def _asset_config(asset_class, symbol):
    """Look up config for a specific asset."""
    global _watchlist_cache
    if _watchlist_cache is None:
        _watchlist_cache = load_watchlist()
    for asset in _watchlist_cache.get(asset_class, []):
        if asset["symbol"] == symbol:
            return asset
    return {"symbol": symbol}


# ── Main ─────────────────────────────────────────────────────────────

def main():
    today_date = datetime.now(ET).date()
    today = today_date.isoformat()

    state = load_state()

    # Crash recovery: if state was saved today but markdown is stale,
    # regenerate it from state before proceeding
    if state.get("last_run_date") == today:
        if not os.path.exists(PAPER_MD):
            print("RECOVERY: paper-trades.md missing, regenerating from state",
                  file=sys.stderr)
            write_paper_md(state, "recovering...")

    try:
        watchlist = load_watchlist()
    except FileNotFoundError:
        print(f"ERROR: watchlist.json not found at {CONFIG_DIR}/watchlist.json", file=sys.stderr)
        sys.exit(1)
    rules = watchlist["rules"]

    # Load education progress
    edu_sections, edu_done, edu_total = load_education_progress()
    edu_status = education_summary(edu_sections, edu_done, edu_total)
    print(f"Education: {edu_status}")

    # Load lessons feedback once (used by analyze + open_trade)
    lessons = load_lessons()

    # Load sentiment scores (used to dampen/veto disagreeing trades)
    sentiment_scores = load_sentiment_for_trading(today)
    if sentiment_scores:
        print(f"Sentiment: {len(sentiment_scores)} symbols loaded")
    else:
        print("Sentiment: no data for today (all trades get 1.0x)")

    # Load and analyze all assets
    analyses = []
    prices = {}
    for asset_class in ["forex", "stocks", "crypto"]:
        for asset in watchlist.get(asset_class, []):
            symbol = asset["symbol"]
            try:
                candles = load_candles(asset_class, symbol,
                                       warn_stale_days=2, max_stale_days=3,
                                       today=today_date)
                if len(candles) < LOOKBACK:
                    print(f"{asset_class:6s} {symbol:6s}: SKIP (only {len(candles)} candles)", file=sys.stderr)
                    continue
                a = analyze(asset_class, symbol, asset, candles, edu_sections,
                            rules, lessons=lessons)
                if a is None:
                    print(f"{asset_class:6s} {symbol:6s}: SKIP (insufficient candle data)", file=sys.stderr)
                    continue
                analyses.append(a)
                prices[(asset_class, symbol)] = (
                    a["last_close"], a["last_high"], a["last_low"],
                )
            except FileNotFoundError:
                print(f"{asset_class:6s} {symbol:6s}: SKIP (no data file yet)", file=sys.stderr)
            except Exception as e:
                print(f"{asset_class:6s} {symbol:6s}: ERROR ({type(e).__name__}) {e}", file=sys.stderr)

    if not analyses:
        print("ERROR: No candle data available", file=sys.stderr)
        sys.exit(1)

    # Build cross rates for accurate pip value on cross pairs (EURJPY, GBPJPY, etc.)
    cross_rates = {}
    for sym_key in ["USDJPY", "USDCHF"]:
        pd = prices.get(("forex", sym_key))
        if pd:
            cross_rates[sym_key] = pd[0]  # last close

    # Step 1: Check stops on open positions
    closed_by_stop = check_stops(state, prices, today, rules=rules, cross_rates=cross_rates)
    for c in closed_by_stop:
        print(f"CLOSED {c['id']} {c['asset_class']}/{c['symbol']} ({c['close_reason']}): ${c['pnl_dollars']:+.2f}")

    # Step 2: Friday weekend close (forex only)
    closed_friday = friday_close(state, prices, today, today_date, rules=rules,
                                  cross_rates=cross_rates)
    for c in closed_friday:
        print(f"CLOSED {c['id']} {c['asset_class']}/{c['symbol']} (weekend): ${c['pnl_dollars']:+.2f}")

    all_closed = closed_by_stop + closed_friday

    # Update peak balance (track high-water mark)
    if state["balance"] > state.get("peak_balance", 10000.0):
        state["peak_balance"] = state["balance"]

    # Step 3: Open new trades — AGGRESSIVE. Fill all available slots.
    # Drawdown circuit breaker: halt new entries if drawdown exceeds limit
    opened = []
    max_dd = rules.get("max_drawdown", 0.50)
    peak = state.get("peak_balance", 10000.0)
    current_dd = (peak - state["balance"]) / peak if peak > 0 else 0
    if current_dd > max_dd:
        print(f"CIRCUIT BREAKER: drawdown {current_dd:.0%} exceeds {max_dd:.0%} limit "
              f"(peak: ${peak:,.2f}, current: ${state['balance']:,.2f}). "
              f"No new entries today.", file=sys.stderr)
    else:
        global_max = rules["max_positions"]["global"]
        class_limits = rules["max_positions"]

        # Equity curve filter: scale back when losing
        ecf = rules.get("equity_curve_filter", {})
        if ecf.get("enabled", False):
            lb = ecf.get("lookback_trades", 10)
            recent_closed = state.get("closed", [])[-lb:]
            if len(recent_closed) >= lb:
                recent_pnl = sum(t.get("pnl_dollars", 0) for t in recent_closed)
                if recent_pnl < 0:
                    reduced = ecf.get("reduced_max_positions", 3)
                    global_max = min(global_max, reduced)
                    print(f"EQUITY CURVE: last {lb} trades net ${recent_pnl:.2f} "
                          f"— reducing max positions to {global_max}")

        for a in analyses:
            if len(state["open"]) >= global_max:
                break
            if a["signal"] is None:
                continue

            ac = a["asset_class"]
            sym = a["symbol"]

            class_count = sum(1 for p in state["open"] if p["asset_class"] == ac)
            if class_count >= class_limits.get(ac, 2):
                continue

            if any(p["symbol"] == sym for p in state["open"]):
                continue

            # Correlation guard: prevent doubling up on correlated positions
            corr_ok, corr_reason = check_correlation_guard(
                ac, sym, a["signal"]["direction"],
                _asset_config(ac, sym), state["open"], rules, watchlist)
            if not corr_ok:
                print(f"SKIP {ac}/{sym}: correlation guard ({corr_reason})")
                continue

            # Earnings proximity guard: skip stocks near earnings dates
            if ac == "stocks":
                dte = days_until_earnings(sym, today_date)
                if dte is not None and 0 <= dte <= EARNINGS_BUFFER_DAYS:
                    print(f"SKIP {ac}/{sym}: earnings in {dte} day(s) — avoiding gap risk")
                    continue

            if lessons:
                sym_data = lessons.get("by_symbol", {}).get(sym, {})
                if sym_data.get("skip", False):
                    print(f"SKIP {ac}/{sym}: negative track record "
                          f"({sym_data.get('count', 0)} trades, "
                          f"{sym_data.get('win_rate', 0):.0%} WR)")
                    continue

            # Sentiment filter: dampen or veto trades disagreeing with news
            sent_mult, sent_reason = compute_sentiment_multiplier(
                sym, a["signal"]["direction"], sentiment_scores, rules)
            if sent_mult == 0.0:
                score = sentiment_scores.get(sym, 0)
                print(f"SKIP {ac}/{sym}: sentiment veto "
                      f"({sent_reason}, score={score:+.3f})")
                continue

            trade = open_trade(state, ac, sym, a["signal"], watchlist, today,
                               lessons=lessons,
                               sentiment_multiplier=sent_mult,
                               regime=a.get("regime"),
                               cross_rates=cross_rates)
            if trade:
                trade["sentiment_multiplier"] = sent_mult
                trade["sentiment_reason"] = sent_reason
                opened.append(trade)
                handler = HANDLERS[ac]
                sent_tag = f" sent:{sent_mult:.1f}x" if sent_mult < 1.0 else ""
                print(
                    f"OPENED {trade['id']} {ac}/{sym} {trade['direction']} "
                    f"@ {trade['entry']:.5f} (SL:{trade['stop_loss']:.5f} "
                    f"TP:{trade['take_profit']:.5f} "
                    f"{handler.format_size(trade['size'])}{sent_tag})"
                )

    # Step 4: Write everything (state first — source of truth)
    state["last_run_date"] = today
    save_state(state)
    write_paper_md(state, edu_status)
    analysis_path = write_daily_analysis(analyses, opened, all_closed, edu_status, today)
    cleanup_old_analyses(today_date)
    append_journal(analyses, opened, all_closed, state["balance"], edu_status, today)

    # Summary
    print(f"\nBalance: ${state['balance']:,.2f}")
    print(f"Open positions: {len(state['open'])}")
    print(f"Assets analyzed: {len(analyses)}")
    print(f"Analysis saved: {analysis_path}")

    if not opened and not all_closed:
        signals = [f"{a['asset_class']}/{a['symbol']}" for a in analyses if a["signal"]]
        if signals:
            print(f"Signals found but position limits reached: {', '.join(signals)}")
        else:
            print("No trade signals today (shouldn't happen — check analysis)")


if __name__ == "__main__":
    main()
