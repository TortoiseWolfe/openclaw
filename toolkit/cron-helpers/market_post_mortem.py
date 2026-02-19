#!/usr/bin/env python3
"""Post-mortem analysis of closed paper trades.

Analyzes every closed trade in paper-state.json:
- Classifies the signal type from the reason field
- Computes time-in-trade and excursion metrics using candle data
- Builds aggregate statistics by signal type, asset class, and symbol
- Writes trade-lessons.json for the trade decision engine to consume

Runs daily Mon-Fri at 9:20 AM ET (5 min after trade decisions).
Designed to be called via a single `exec` tool call from the cron job.
"""

import json
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trading_common import (
    classify_signal, load_candles_safe as load_candles,
    atomic_json_write,
    DATA_DIR, PRIVATE_DIR, STATE_FILE, LESSONS_FILE, JOURNAL,
)

MIN_SAMPLE_SIZE = 3
SYMBOL_SKIP_MIN_TRADES = 5
SYMBOL_SKIP_MAX_WIN_RATE = 0.30
POST_CLOSE_LOOKBACK = 5  # candles after close for trend continuation


# ── Per-trade analysis ───────────────────────────────────────────────

def analyze_trade(trade, candles):
    """Analyze a single closed trade against its candle data.

    Returns a detail dict with MAE, MFE, trend continuation, etc.
    """
    entry = trade["entry"]
    exit_price = trade["exit"]
    direction = trade["direction"]
    stop_loss = trade["stop_loss"]
    date_opened = trade["date_opened"]
    date_closed = trade["date_closed"]

    time_in_trade = (date.fromisoformat(date_closed) -
                     date.fromisoformat(date_opened)).days

    # Candles during the trade
    trade_candles = [c for c in candles
                     if date_opened <= c["date"] <= date_closed]

    mae = None
    mfe = None
    if trade_candles:
        if direction == "LONG":
            mae = max((entry - c["l"]) / entry for c in trade_candles)
            mfe = max((c["h"] - entry) / entry for c in trade_candles)
        else:
            mae = max((c["h"] - entry) / entry for c in trade_candles)
            mfe = max((entry - c["l"]) / entry for c in trade_candles)

    # Trend continuation: check candles AFTER close
    post_close = [c for c in candles if c["date"] > date_closed]
    post_close = post_close[:POST_CLOSE_LOOKBACK]
    trend_continued = None
    if len(post_close) >= 3:
        if direction == "LONG":
            trend_continued = post_close[-1]["c"] > exit_price
        else:
            trend_continued = post_close[-1]["c"] < exit_price

    stop_distance_pct = abs(entry - stop_loss) / entry if entry > 0 else 0

    # Risk amount for RR calculation
    risk = abs(entry - stop_loss) * trade["size"]
    rr_achieved = round(trade["pnl_dollars"] / risk, 4) if risk > 0 else 0

    stopped_on_noise = (trade["close_reason"] == "stop loss"
                        and trend_continued is True)

    return {
        "id": trade["id"],
        "signal_type": classify_signal(trade.get("reason", "")),
        "asset_class": trade["asset_class"],
        "symbol": trade["symbol"],
        "direction": direction,
        "pnl_dollars": trade["pnl_dollars"],
        "close_reason": trade["close_reason"],
        "entry_date": date_opened,
        "close_date": date_closed,
        "time_in_trade_days": time_in_trade,
        "max_adverse_excursion_pct": round(mae, 5) if mae is not None else None,
        "max_favorable_excursion_pct": round(mfe, 5) if mfe is not None else None,
        "trend_continued": trend_continued,
        "stop_distance_pct": round(stop_distance_pct, 5),
        "rr_achieved": rr_achieved,
        "stopped_on_noise": stopped_on_noise,
    }


# ── Confidence multiplier ───────────────────────────────────────────

def compute_confidence_multiplier(count, win_rate, rr_ratio=1.5):
    """Compute position-sizing confidence multiplier from track record.

    Breakeven win rate for 1.5 RR is ~40%. Multiplier adjusts based on
    how far the actual win rate deviates from breakeven.

    Ramp: <3 trades = 1.0, 3-9 = gentle (0.75-1.25), 10+ = full (0.25-1.5).
    """
    if count < MIN_SAMPLE_SIZE:
        return 1.0

    breakeven = 1.0 / (1.0 + rr_ratio)  # ~0.4 for 1.5 RR
    deviation = win_rate - breakeven
    raw = 1.0 + (deviation / 0.5) * 0.5

    if count < 10:
        raw = max(0.75, min(1.25, raw))
    else:
        raw = max(0.25, min(1.5, raw))

    return round(raw, 4)


# ── Aggregate builders ───────────────────────────────────────────────

def build_signal_stats(details):
    """Aggregate trade details by signal type."""
    groups = {}
    for d in details:
        st = d["signal_type"]
        if st not in groups:
            groups[st] = []
        groups[st].append(d)

    result = {}
    for st, trades in groups.items():
        count = len(trades)
        wins = [t for t in trades if t["pnl_dollars"] > 0]
        losses = [t for t in trades if t["pnl_dollars"] < 0]
        win_rate = len(wins) / count if count > 0 else 0
        avg_pnl = sum(t["pnl_dollars"] for t in trades) / count if count > 0 else 0

        avg_win = (sum(t["pnl_dollars"] for t in wins) / len(wins)) if wins else 0
        avg_loss = (sum(t["pnl_dollars"] for t in losses) / len(losses)) if losses else 0

        rr_values = [t["rr_achieved"] for t in trades if t["rr_achieved"] is not None]
        avg_rr = sum(rr_values) / len(rr_values) if rr_values else 0

        time_values = [t["time_in_trade_days"] for t in trades]
        avg_time = sum(time_values) / len(time_values) if time_values else 0

        noise_count = sum(1 for t in trades if t.get("stopped_on_noise", False))

        result[st] = {
            "count": count,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 3),
            "avg_pnl": round(avg_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "avg_rr_achieved": round(avg_rr, 4),
            "avg_time_in_trade_days": round(avg_time, 1),
            "stop_too_tight_pct": round(noise_count / count, 3) if count > 0 else 0,
            "confidence_multiplier": compute_confidence_multiplier(count, win_rate),
        }

    return result


def build_class_stats(details):
    """Aggregate trade details by asset class."""
    groups = {}
    for d in details:
        ac = d["asset_class"]
        if ac not in groups:
            groups[ac] = []
        groups[ac].append(d)

    result = {}
    for ac, trades in groups.items():
        count = len(trades)
        wins = sum(1 for t in trades if t["pnl_dollars"] > 0)
        win_rate = wins / count if count > 0 else 0
        avg_pnl = sum(t["pnl_dollars"] for t in trades) / count if count > 0 else 0

        result[ac] = {
            "count": count,
            "wins": wins,
            "losses": count - wins,
            "win_rate": round(win_rate, 3),
            "avg_pnl": round(avg_pnl, 2),
            "confidence_multiplier": compute_confidence_multiplier(count, win_rate),
        }

    return result


SKIP_DECAY_DAYS = 30       # clear skip flag if last loss > 30 days ago
SKIP_ROLLING_WINDOW = 10   # use last N trades for skip decision


def build_symbol_stats(details):
    """Aggregate trade details by symbol. Flag persistent losers for skip.

    Uses a rolling window of the last SKIP_ROLLING_WINDOW trades and
    a decay mechanism: skip flags are cleared if the most recent loss
    is older than SKIP_DECAY_DAYS days.
    """
    groups = {}
    for d in details:
        sym = d["symbol"]
        if sym not in groups:
            groups[sym] = []
        groups[sym].append(d)

    result = {}
    today = date.today()
    for sym, trades in groups.items():
        sorted_trades = sorted(trades, key=lambda t: t["close_date"], reverse=True)

        # Rolling window for skip decision
        recent = sorted_trades[:SKIP_ROLLING_WINDOW]
        count = len(trades)
        recent_count = len(recent)
        wins = sum(1 for t in recent if t["pnl_dollars"] > 0)
        win_rate = wins / recent_count if recent_count > 0 else 0
        avg_pnl = (sum(t["pnl_dollars"] for t in recent) / recent_count
                   if recent_count > 0 else 0)

        # All-time stats for reporting
        all_wins = sum(1 for t in trades if t["pnl_dollars"] > 0)
        all_avg_pnl = sum(t["pnl_dollars"] for t in trades) / count if count > 0 else 0

        # Streak: count consecutive wins/losses from most recent
        streak = 0
        if sorted_trades:
            direction = 1 if sorted_trades[0]["pnl_dollars"] > 0 else -1
            for t in sorted_trades:
                if (t["pnl_dollars"] > 0) == (direction > 0):
                    streak += direction
                else:
                    break

        # Last loss date for decay
        losses = [t for t in sorted_trades if t["pnl_dollars"] <= 0]
        last_loss_date = losses[0]["close_date"] if losses else None

        # Skip decision: recent window + decay
        skip = (recent_count >= SYMBOL_SKIP_MIN_TRADES
                and win_rate < SYMBOL_SKIP_MAX_WIN_RATE
                and avg_pnl < 0)

        # Decay: clear skip if last loss is old enough
        if skip and last_loss_date:
            days_since_loss = (today - date.fromisoformat(last_loss_date)).days
            if days_since_loss > SKIP_DECAY_DAYS:
                skip = False

        result[sym] = {
            "count": count,
            "wins": all_wins,
            "losses": count - all_wins,
            "win_rate": round(win_rate, 3),
            "avg_pnl": round(all_avg_pnl, 2),
            "recent_win_rate": round(win_rate, 3),
            "recent_avg_pnl": round(avg_pnl, 2),
            "streak": streak,
            "last_loss_date": last_loss_date,
            "skip": skip,
        }

    return result


def compute_stop_analysis(details):
    """Analyze stop-loss performance across all trades.

    Determines if stops are systematically too tight (noise stops) and
    computes an optimal multiplier to widen them if needed.
    """
    sl_trades = [d for d in details if d["close_reason"] == "stop loss"]
    if not sl_trades:
        return {
            "avg_stop_distance_pct": 0,
            "stopped_out_on_noise_pct": 0,
            "optimal_stop_multiplier": 1.0,
        }

    noise_count = sum(1 for d in sl_trades if d.get("stopped_on_noise", False))
    noise_pct = noise_count / len(sl_trades)

    stop_dists = [d["stop_distance_pct"] for d in sl_trades
                  if d["stop_distance_pct"] > 0]
    avg_stop_dist = sum(stop_dists) / len(stop_dists) if stop_dists else 0

    # Widen stops if >30% are noise, with enough data
    if noise_pct > 0.3 and len(sl_trades) >= MIN_SAMPLE_SIZE:
        multiplier = 1.0 + (noise_pct - 0.3) * 0.5
        multiplier = min(1.5, multiplier)
    else:
        multiplier = 1.0

    return {
        "avg_stop_distance_pct": round(avg_stop_dist, 5),
        "stopped_out_on_noise_pct": round(noise_pct, 3),
        "optimal_stop_multiplier": round(multiplier, 2),
    }


# ── Output ───────────────────────────────────────────────────────────

def write_lessons(lessons):
    """Write trade-lessons.json atomically."""
    atomic_json_write(LESSONS_FILE, lessons)


def append_journal_entry(details, signal_stats, symbol_stats, stop_analysis):
    """Append a post-mortem summary to trade-journal.md."""
    today = date.today().isoformat()

    # Check for duplicate entry
    try:
        with open(JOURNAL, encoding="utf-8") as f:
            if f"### {today} — Post-Mortem" in f.read():
                return  # already written today
    except FileNotFoundError:
        pass

    lines = [
        f"### {today} — Post-Mortem Analysis",
        f"**Trades analyzed**: {len(details)} total",
    ]

    # Signal performance
    if signal_stats:
        parts = []
        for st in sorted(signal_stats, key=lambda s: signal_stats[s]["count"],
                         reverse=True):
            s = signal_stats[st]
            parts.append(f"{st}: {s['win_rate']:.0%} WR ({s['count']} trades)")
        lines.append(f"**Signal performance**: {', '.join(parts)}")

        best = max(signal_stats.items(), key=lambda x: x[1]["avg_pnl"])
        worst = min(signal_stats.items(), key=lambda x: x[1]["avg_pnl"])
        lines.append(f"**Best signal**: {best[0]} (${best[1]['avg_pnl']:+.2f} avg)")
        lines.append(f"**Worst signal**: {worst[0]} (${worst[1]['avg_pnl']:+.2f} avg)")

    # Skipped symbols
    skipped = [sym for sym, s in symbol_stats.items() if s.get("skip")]
    if skipped:
        skip_parts = [f"{sym} ({symbol_stats[sym]['count']} trades, "
                      f"{symbol_stats[sym]['win_rate']:.0%} WR)"
                      for sym in skipped]
        lines.append(f"**Symbols skipped**: {', '.join(skip_parts)}")

    # Stop analysis
    if stop_analysis["stopped_out_on_noise_pct"] > 0:
        lines.append(
            f"**Stop analysis**: {stop_analysis['stopped_out_on_noise_pct']:.0%} "
            f"noise stops, buffer multiplier: {stop_analysis['optimal_stop_multiplier']}"
        )

    # Active feedback
    active = []
    for st, s in signal_stats.items():
        if s["confidence_multiplier"] != 1.0:
            active.append(f"{st}: x{s['confidence_multiplier']}")
    if active or skipped:
        feedback_parts = []
        if active:
            feedback_parts.append(f"multipliers: {', '.join(active)}")
        if skipped:
            feedback_parts.append(f"{len(skipped)} symbol(s) on skip list")
        lines.append(f"**Feedback active**: {'; '.join(feedback_parts)}")
    else:
        lines.append("**Feedback active**: none yet (insufficient data)")

    lines.append("")

    os.makedirs(PRIVATE_DIR, exist_ok=True)
    with open(JOURNAL, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    # Load state
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        print("ERROR: paper-state.json not found", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in paper-state.json: {e}", file=sys.stderr)
        sys.exit(1)

    closed = state.get("closed", [])
    if not closed:
        print("No closed trades to analyze.")
        write_lessons({
            "generated": datetime.now().isoformat(timespec="seconds"),
            "trade_count": 0,
            "by_signal_type": {},
            "by_asset_class": {},
            "by_symbol": {},
            "stop_analysis": {
                "avg_stop_distance_pct": 0,
                "stopped_out_on_noise_pct": 0,
                "optimal_stop_multiplier": 1.0,
            },
            "trade_details": [],
        })
        return

    # Load candle data for each traded symbol
    candle_cache = {}
    for trade in closed:
        key = (trade["asset_class"], trade["symbol"])
        if key not in candle_cache:
            candle_cache[key] = load_candles(*key)

    # Analyze each closed trade
    details = []
    for trade in closed:
        key = (trade["asset_class"], trade["symbol"])
        candles = candle_cache.get(key, [])
        detail = analyze_trade(trade, candles)
        details.append(detail)

    # Build aggregates
    signal_stats = build_signal_stats(details)
    class_stats = build_class_stats(details)
    symbol_stats = build_symbol_stats(details)
    stop_analysis = compute_stop_analysis(details)

    # Build lessons file — keep only the most recent 200 trades to prevent
    # unbounded growth; aggregates already capture the full history
    MAX_TRADE_DETAILS = 200
    recent_details = details[-MAX_TRADE_DETAILS:] if len(details) > MAX_TRADE_DETAILS else details
    lessons = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "trade_count": len(details),
        "by_signal_type": signal_stats,
        "by_asset_class": class_stats,
        "by_symbol": symbol_stats,
        "stop_analysis": stop_analysis,
        "trade_details": recent_details,
    }

    write_lessons(lessons)
    append_journal_entry(details, signal_stats, symbol_stats, stop_analysis)

    # Print summary
    print(f"Post-mortem: {len(details)} closed trades analyzed")
    for st in sorted(signal_stats, key=lambda s: signal_stats[s]["count"],
                     reverse=True):
        s = signal_stats[st]
        print(f"  {st:16s}: {s['count']} trades, {s['win_rate']:.0%} WR, "
              f"avg ${s['avg_pnl']:+.2f} (confidence: {s['confidence_multiplier']})")

    skipped = [sym for sym, s in symbol_stats.items() if s.get("skip")]
    if skipped:
        print(f"  Skipped symbols: {', '.join(skipped)}")

    if stop_analysis["stopped_out_on_noise_pct"] > 0:
        print(f"  Stop analysis: {stop_analysis['stopped_out_on_noise_pct']:.0%} "
              f"noise stops, multiplier: {stop_analysis['optimal_stop_multiplier']}")

    print(f"\nLessons written to {LESSONS_FILE}")


if __name__ == "__main__":
    main()
