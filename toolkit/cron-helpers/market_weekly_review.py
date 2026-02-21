#!/usr/bin/env python3
"""Weekly paper trading performance review.

Reads paper-state.json, calculates weekly stats (trades opened/closed,
win rate, P&L by asset class), and appends a weekly review entry to
trade-journal.md.

Designed to be called via a single `exec` tool call from the cron job.
"""

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trading_common import PRIVATE_DIR, STATE_FILE, JOURNAL, ET


def load_state():
    """Load paper trading state."""
    with open(STATE_FILE, encoding="utf-8") as f:
        return json.load(f)


def week_bounds(today=None):
    """Return (monday, sunday) date strings for the current week."""
    if today is None:
        today = datetime.now(ET).date()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


def filter_week(trades, start, end):
    """Filter trades to those with date_opened within [start, end]."""
    result = []
    for t in trades:
        d = t.get("date_opened", "")
        if start <= d <= end:
            result.append(t)
    return result


def filter_closed_week(trades, start, end):
    """Filter closed trades to those with date_closed within [start, end]."""
    result = []
    for t in trades:
        d = t.get("date_closed", "")
        if start <= d <= end:
            result.append(t)
    return result


def calc_stats(closed_this_week):
    """Calculate win/loss stats from closed trades."""
    if not closed_this_week:
        return {
            "wins": 0, "losses": 0, "total_pnl": 0.0,
            "best": None, "worst": None, "by_class": {},
        }

    wins = [t for t in closed_this_week if t.get("pnl_dollars", 0) > 0]
    losses = [t for t in closed_this_week if t.get("pnl_dollars", 0) < 0]
    total_pnl = sum(t.get("pnl_dollars", 0) for t in closed_this_week)

    best = max(closed_this_week, key=lambda t: t.get("pnl_dollars", 0))
    worst = min(closed_this_week, key=lambda t: t.get("pnl_dollars", 0))

    by_class = {}
    for t in closed_this_week:
        ac = t.get("asset_class", "unknown")
        if ac not in by_class:
            by_class[ac] = {"count": 0, "pnl": 0.0}
        by_class[ac]["count"] += 1
        by_class[ac]["pnl"] += t.get("pnl_dollars", 0)

    return {
        "wins": len(wins),
        "losses": len(losses),
        "total_pnl": total_pnl,
        "best": best,
        "worst": worst,
        "by_class": by_class,
    }


def count_by_class(trades):
    """Count trades grouped by asset_class."""
    counts = {}
    for t in trades:
        ac = t.get("asset_class", "unknown")
        counts[ac] = counts.get(ac, 0) + 1
    return counts


def format_trade_line(trade):
    """Format a single trade reference."""
    tid = trade.get("id", "?")
    sym = trade.get("symbol", "?")
    direction = trade.get("direction", "?")
    pnl = trade.get("pnl_dollars", 0)
    return f"{tid} {sym} {direction} {pnl:+.2f}"


def build_review(state, today=None):
    """Build the weekly review entry lines and summary."""
    if today is None:
        today = datetime.now(ET).date()

    mon_iso, sun_iso = week_bounds(today)
    monday = date.fromisoformat(mon_iso)
    friday = monday + timedelta(days=4)

    all_trades = state.get("open", []) + state.get("closed", [])
    opened_this_week = filter_week(all_trades, mon_iso, sun_iso)
    closed_this_week = filter_closed_week(state.get("closed", []), mon_iso, sun_iso)

    opened_counts = count_by_class(opened_this_week)
    stats = calc_stats(closed_this_week)
    balance = state.get("balance", 10000.0)

    # Format week range
    week_str = f"{monday.strftime('%b %d')} – {friday.strftime('%b %d, %Y')}"

    lines = [
        f"### {today.isoformat()} — Weekly Review",
        f"**Week**: {week_str}",
    ]

    # Trades opened
    if opened_this_week:
        class_parts = ", ".join(f"{ac}: {n}" for ac, n in sorted(opened_counts.items()))
        lines.append(f"**Trades opened**: {len(opened_this_week)} ({class_parts})")
    else:
        lines.append("**Trades opened**: 0")

    # Trades closed
    lines.append(f"**Trades closed**: {len(closed_this_week)}")

    # Win rate
    if closed_this_week:
        total = stats["wins"] + stats["losses"]
        pct = (stats["wins"] / total * 100) if total > 0 else 0
        lines.append(f"**Win rate**: {pct:.0f}% ({stats['wins']}W / {stats['losses']}L)")
        lines.append(f"**Weekly P&L**: ${stats['total_pnl']:+,.2f}")

        if stats["best"]:
            lines.append(f"**Best trade**: {format_trade_line(stats['best'])}")
        if stats["worst"]:
            lines.append(f"**Worst trade**: {format_trade_line(stats['worst'])}")

        # Breakdown by asset class
        if stats["by_class"]:
            parts = []
            for ac in sorted(stats["by_class"]):
                info = stats["by_class"][ac]
                parts.append(f"{ac}: {info['count']} trades, ${info['pnl']:+,.2f}")
            lines.append(f"**By class**: {'; '.join(parts)}")
    else:
        lines.append("**Win rate**: N/A")

    lines.append(f"**Balance**: ${balance:,.2f}")

    # Notes
    if not opened_this_week and not closed_this_week:
        lines.append("**Notes**: No signals met entry criteria. Conservative conditions holding.")
    elif closed_this_week and stats["total_pnl"] > 0:
        lines.append("**Notes**: Positive week. Review winning patterns for consistency.")
    elif closed_this_week and stats["total_pnl"] <= 0:
        lines.append("**Notes**: Negative week. Review losing trades for pattern.")
    else:
        lines.append("**Notes**: Trades opened but none closed this week.")

    lines.append("")
    return lines


def check_duplicate(today=None):
    """Check if a weekly review for this date already exists."""
    if today is None:
        today = datetime.now(ET).date()
    marker = f"### {today.isoformat()} — Weekly Review"
    try:
        with open(JOURNAL) as f:
            return marker in f.read()
    except FileNotFoundError:
        return False


def main():
    try:
        state = load_state()
    except FileNotFoundError:
        print("ERROR: paper-state.json not found", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in paper-state.json: {e}", file=sys.stderr)
        sys.exit(1)

    today = datetime.now(ET).date()

    if check_duplicate(today):
        print(f"Weekly review for {today.isoformat()} already exists, skipping.")
        return

    review_lines = build_review(state, today)

    # Append to journal
    os.makedirs(PRIVATE_DIR, exist_ok=True)
    with open(JOURNAL, "a") as f:
        f.write("\n".join(review_lines) + "\n")

    # Print summary to stdout for model to report
    for line in review_lines:
        if line.startswith("**"):
            print(line.replace("**", ""))

    print(f"\nWeekly review appended to trade-journal.md")


if __name__ == "__main__":
    main()
