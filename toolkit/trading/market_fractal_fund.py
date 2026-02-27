#!/usr/bin/env python3
"""Fractal paper fund — independent paper trading using Williams Fractal breakouts.

Runs as a separate cron job from the main fund. Separate state file,
separate balance, separate positions. Shares candle data and watchlist
(read-only).

Usage:
    python3 market_fractal_fund.py
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trading_common import (
    load_watchlist, load_candles, classify_signal,
    check_correlation_guard, atomic_json_write,
    FRACTAL_STATE_FILE, PRIVATE_DIR, ET,
)
from trading_handlers import HANDLERS
from trading_fractals import fractal_signal
from trading_signals import compute_atr
from market_trade_decision import (
    check_stops, friday_close, _asset_config, _get_slippage,
)


# ── Fund rules ──────────────────────────────────────────────────────

INITIAL_BALANCE = 5000.0

FRACTAL_RULES = {
    "max_risk": 0.02,
    "rr_ratio": 2.0,
    "max_drawdown": 0.30,
    "max_positions": {
        "forex": 2,
        "stocks": 3,
        "crypto": 1,
        "global": 5,
    },
    "max_leverage": 5,
    "trailing_stop": {
        "enabled": True,
        "activation_rr": 1.0,
        "atr_multiplier": 2.0,
    },
    "spread": {
        "forex": 0.00015,
        "stocks": 0.02,
        "crypto_pct": 0.0015,
    },
    "slippage": {
        "forex": 0.00005,
        "stocks": 0.01,
        "crypto_pct": 0.0005,
    },
    "atr_stops": {
        "enabled": True,
        "multiplier": 1.5,
    },
    "fractal_window": 2,
    "fractal_lookback": 3,
    "correlation": {
        "enabled": True,
        "forex_max_same_currency": 1,
        "stock_max_same_group": 1,
    },
}

FRACTAL_MD = os.path.join(PRIVATE_DIR, "fractal-trades.md")
FRACTAL_JOURNAL = os.path.join(PRIVATE_DIR, "fractal-journal.md")


# ── State management ────────────────────────────────────────────────

def load_state():
    if os.path.exists(FRACTAL_STATE_FILE):
        with open(FRACTAL_STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
        if "peak_balance" not in state:
            state["peak_balance"] = max(state["balance"], INITIAL_BALANCE)
        return state
    return {
        "balance": INITIAL_BALANCE,
        "peak_balance": INITIAL_BALANCE,
        "next_id": 1,
        "open": [],
        "closed": [],
    }


def save_state(state):
    atomic_json_write(FRACTAL_STATE_FILE, state)


# ── Trade opening (F-prefix IDs, fractal rules) ────────────────────

def open_fractal_trade(state, asset_class, symbol, signal, watchlist,
                       today, cross_rates=None, atr_at_entry=None):
    """Open a new fractal fund trade. Uses F-prefix IDs."""
    handler = HANDLERS[asset_class]
    config = _asset_config(asset_class, symbol)
    rules = FRACTAL_RULES

    slip = _get_slippage(rules, asset_class, signal["entry"])
    if signal["direction"] == "LONG":
        entry = signal["entry"] + slip
        stop_loss = signal["stop_loss"] - slip
    else:
        entry = signal["entry"] - slip
        stop_loss = signal["stop_loss"] + slip
    take_profit = signal["take_profit"]

    stop_distance = abs(entry - stop_loss)
    size = handler.position_size(
        state["balance"], rules["max_risk"],
        stop_distance, entry,
        symbol, config, cross_rates=cross_rates,
    )
    if size == 0:
        return None

    max_leverage = rules.get("max_leverage", 5)
    notional = size * entry
    max_notional = state["balance"] * max_leverage
    if notional > max_notional and max_notional > 0:
        size = max(1, int(max_notional / entry))

    trade = {
        "id": "F%03d" % state["next_id"],
        "date_opened": today,
        "asset_class": asset_class,
        "symbol": symbol,
        "direction": signal["direction"],
        "entry": round(entry, 5),
        "stop_loss": round(stop_loss, 5),
        "original_stop_loss": round(stop_loss, 5),
        "take_profit": round(take_profit, 5),
        "size": size,
        "reason": signal["reason"],
    }
    if atr_at_entry is not None:
        trade["atr_at_entry"] = round(atr_at_entry, 6)
        if signal["direction"] == "LONG":
            trade["high_water_mark"] = round(entry, 5)
        else:
            trade["low_water_mark"] = round(entry, 5)
    state["open"].append(trade)
    state["next_id"] += 1
    return trade


# ── Markdown output ─────────────────────────────────────────────────

def write_fractal_md(state):
    """Write fractal fund summary markdown."""
    lines = ["# Fractal Fund Paper Trades", ""]
    lines.append("**Strategy:** Williams Fractal Breakout")
    lines.append("**Balance:** $%s" % format(state["balance"], ",.2f"))
    lines.append("**Peak:** $%s" % format(state.get("peak_balance", INITIAL_BALANCE), ",.2f"))
    lines.append("**Open:** %d | **Closed:** %d" % (len(state["open"]), len(state["closed"])))
    lines.append("")

    if state["open"]:
        lines.append("## Open Positions")
        lines.append("")
        for p in state["open"]:
            pnl = p.get("unrealized_pnl", 0)
            pnl_str = "+$%.2f" % pnl if pnl >= 0 else "-$%.2f" % abs(pnl)
            lines.append("- **%s** %s/%s %s @ %.5f (SL:%.5f TP:%.5f) %s" % (
                p["id"], p["asset_class"], p["symbol"], p["direction"],
                p["entry"], p["stop_loss"], p["take_profit"], pnl_str))
        lines.append("")

    if state["closed"]:
        lines.append("## Recent Closed (last 10)")
        lines.append("")
        for c in state["closed"][-10:]:
            pnl = c.get("pnl_dollars", 0)
            pnl_str = "+$%.2f" % pnl if pnl >= 0 else "-$%.2f" % abs(pnl)
            lines.append("- **%s** %s/%s %s → %s (%s)" % (
                c["id"], c["asset_class"], c["symbol"],
                c["direction"], pnl_str, c.get("close_reason", "?")))
        lines.append("")

    atomic_json_write.__func__ if hasattr(atomic_json_write, '__func__') else None
    with open(FRACTAL_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def append_fractal_journal(opened, closed, balance, today):
    """Append today's fractal fund activity to the journal."""
    if not opened and not closed:
        return
    lines = ["", "## %s" % today, ""]
    for t in opened:
        lines.append("- OPENED %s %s/%s %s @ %.5f — %s" % (
            t["id"], t["asset_class"], t["symbol"],
            t["direction"], t["entry"], t["reason"]))
    for c in closed:
        pnl = c.get("pnl_dollars", 0)
        lines.append("- CLOSED %s %s/%s %s%s ($%+.2f)" % (
            c["id"], c["asset_class"], c["symbol"],
            c["direction"], " " + c.get("close_reason", ""), pnl))
    lines.append("")
    lines.append("Balance: $%s" % format(balance, ",.2f"))
    lines.append("")
    with open(FRACTAL_JOURNAL, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ── Main ────────────────────────────────────────────────────────────

def main():
    today_date = datetime.now(ET).date()
    today = today_date.isoformat()

    state = load_state()
    watchlist = load_watchlist()
    rules = FRACTAL_RULES

    # Idempotency: skip if already ran today
    if state.get("last_run_date") == today:
        print("Fractal fund already ran today (%s). Skipping." % today)
        return

    print("=== Fractal Fund (%s) ===" % today)
    print("Balance: $%s | Open: %d | Closed: %d" % (
        format(state["balance"], ",.2f"), len(state["open"]), len(state["closed"])))

    # Load candle data and prices for all assets
    prices = {}
    signals = []

    for ac in ["forex", "stocks", "crypto"]:
        for asset in watchlist.get(ac, []):
            sym = asset["symbol"] if isinstance(asset, dict) else asset
            config = asset if isinstance(asset, dict) else {"symbol": sym}
            try:
                candles = load_candles(ac, sym)
                if not candles:
                    continue
                last = candles[-1]
                prices[(ac, sym)] = (last["c"], last["h"], last["l"])

                atr_val = compute_atr(candles, 14)
                sig = fractal_signal(candles, rules, HANDLERS[ac], sym, config)
                if sig:
                    signals.append({
                        "asset_class": ac,
                        "symbol": sym,
                        "signal": sig,
                        "atr": atr_val,
                        "config": config,
                    })
            except FileNotFoundError:
                pass
            except Exception as e:
                print("%s %s: ERROR %s" % (ac, sym, e), file=sys.stderr)

    # Build cross rates
    cross_rates = {}
    for sym_key in ["USDJPY", "USDCHF"]:
        pd = prices.get(("forex", sym_key))
        if pd:
            cross_rates[sym_key] = pd[0]

    # Step 1: Check stops
    closed_by_stop = check_stops(state, prices, today, rules=rules,
                                 cross_rates=cross_rates)
    for c in closed_by_stop:
        print("CLOSED %s %s/%s (%s): $%+.2f" % (
            c["id"], c["asset_class"], c["symbol"],
            c["close_reason"], c["pnl_dollars"]))

    # Step 2: Friday close
    closed_friday = friday_close(state, prices, today, today_date,
                                 rules=rules, cross_rates=cross_rates)
    for c in closed_friday:
        print("CLOSED %s %s/%s (weekend): $%+.2f" % (
            c["id"], c["asset_class"], c["symbol"], c["pnl_dollars"]))

    all_closed = closed_by_stop + closed_friday

    # Update peak balance
    if state["balance"] > state.get("peak_balance", INITIAL_BALANCE):
        state["peak_balance"] = state["balance"]

    # Step 3: Open new trades
    opened = []
    max_dd = rules.get("max_drawdown", 0.30)
    peak = state.get("peak_balance", INITIAL_BALANCE)
    current_dd = (peak - state["balance"]) / peak if peak > 0 else 0

    if current_dd > max_dd:
        print("CIRCUIT BREAKER: drawdown %.0f%% exceeds %.0f%% limit" % (
            current_dd * 100, max_dd * 100))
    else:
        global_max = rules["max_positions"]["global"]
        class_limits = rules["max_positions"]

        for s in signals:
            if len(state["open"]) >= global_max:
                break

            ac = s["asset_class"]
            sym = s["symbol"]

            class_count = sum(1 for p in state["open"] if p["asset_class"] == ac)
            if class_count >= class_limits.get(ac, 2):
                continue

            if any(p["symbol"] == sym for p in state["open"]):
                continue

            # Correlation guard
            corr_cfg = rules.get("correlation", {})
            if corr_cfg.get("enabled", False):
                corr_ok, corr_reason = check_correlation_guard(
                    ac, sym, s["signal"]["direction"],
                    s["config"], state["open"], rules, watchlist)
                if not corr_ok:
                    print("SKIP %s/%s: correlation (%s)" % (ac, sym, corr_reason))
                    continue

            trade = open_fractal_trade(
                state, ac, sym, s["signal"], watchlist, today,
                cross_rates=cross_rates, atr_at_entry=s.get("atr"))
            if trade:
                opened.append(trade)
                handler = HANDLERS[ac]
                print("OPENED %s %s/%s %s @ %.5f (SL:%.5f TP:%.5f %s)" % (
                    trade["id"], ac, sym, trade["direction"],
                    trade["entry"], trade["stop_loss"], trade["take_profit"],
                    handler.format_size(trade["size"])))

    # Step 4: Write state
    state["last_run_date"] = today
    save_state(state)
    write_fractal_md(state)
    append_fractal_journal(opened, all_closed, state["balance"], today)

    # Summary
    print("\nFractal Fund Balance: $%s" % format(state["balance"], ",.2f"))
    print("Open: %d | Signals today: %d | Opened: %d | Closed: %d" % (
        len(state["open"]), len(signals), len(opened), len(all_closed)))


if __name__ == "__main__":
    main()
