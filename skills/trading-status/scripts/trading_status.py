#!/usr/bin/env python3
"""Trading system dashboard — compact two-column status summary.

Reads paper-state.json, fractal-state.json, trade-lessons.json,
curriculum-progress.md, watchlist.json, and validation reports.

All reads are best-effort — missing files produce "N/A" lines, not crashes.
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except ImportError:
    ET = timezone(timedelta(hours=-5))


def find_repo_root():
    """Walk up from this script to find the repo root (contains trading-data/)."""
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(10):
        if os.path.isdir(os.path.join(d, "trading-data")):
            return d
        d = os.path.dirname(d)
    return None


REPO = find_repo_root()
if REPO is None:
    print("ERROR: Could not find repo root (no trading-data/ directory)")
    sys.exit(1)

PRIVATE = os.path.join(REPO, "trading-data", "private")
CONFIG = os.path.join(REPO, "trading-data", "config")
EDU = os.path.join(REPO, "trading-data", "education")

COL_W = 38  # column width for side-by-side


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def load_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


# ── Fund stats ───────────────────────────────────────────────────────

def _fund_stats(state, lessons=None):
    """Extract key numbers from a fund's state + optional lessons."""
    if state is None:
        return None

    balance = state.get("balance", 0)
    peak = state.get("peak_balance", 10000.0)
    dd_pct = (peak - balance) / peak * 100 if peak > 0 else 0
    open_pos = state.get("open", [])
    closed = state.get("closed", [])
    unrealized = sum(p.get("unrealized_pnl", 0) for p in open_pos)
    equity = balance + unrealized

    # Performance from lessons (rich) or closed trades (basic)
    if lessons and lessons.get("trade_count", 0) > 0:
        count = lessons["trade_count"]
        total_wins = sum(d.get("wins", 0) for d in lessons.get("by_signal_type", {}).values())
        total_losses = sum(d.get("losses", 0) for d in lessons.get("by_signal_type", {}).values())
        total_pnl = sum(d.get("avg_pnl", 0) * d.get("count", 0)
                        for d in lessons.get("by_signal_type", {}).values())
    elif closed:
        count = len(closed)
        total_wins = sum(1 for t in closed if t.get("pnl_dollars", 0) > 0)
        total_losses = count - total_wins
        total_pnl = sum(t.get("pnl_dollars", 0) for t in closed)
    else:
        count = 0
        total_wins = total_losses = 0
        total_pnl = 0.0

    wr = total_wins / count * 100 if count > 0 else 0

    return {
        "balance": balance, "equity": equity, "unrealized": unrealized,
        "peak": peak, "dd_pct": dd_pct,
        "n_open": len(open_pos), "n_closed": len(closed),
        "trades": count, "wins": total_wins, "losses": total_losses,
        "wr": wr, "total_pnl": total_pnl,
    }


def _fund_column(label, stats):
    """Return list of formatted lines for one fund column."""
    if stats is None:
        return [label, "N/A — state file not found", "", "", "", ""]

    unr = stats["unrealized"]
    pnl = stats["total_pnl"]
    return [
        label,
        f"Balance:  {_dollar(stats['balance'])}",
        f"Equity:   {_dollar(stats['equity'])} ({_signed_dollar(unr)})",
        f"Peak:     {_dollar(stats['peak'])} (DD {stats['dd_pct']:.0f}%)",
        f"Open: {stats['n_open']}  Closed: {stats['n_closed']}",
        f"WR: {stats['wr']:.0f}% ({stats['wins']}W/{stats['losses']}L) "
        f"P&L: {_signed_dollar(pnl)}",
    ]


def _dollar(n):
    """Format dollar amount compactly (no sign prefix)."""
    if abs(n) >= 1000:
        return f"${abs(n):,.0f}"
    return f"${abs(n):,.2f}"


def _signed_dollar(n):
    """Format dollar amount with explicit +/- sign."""
    sign = "+" if n >= 0 else "-"
    if abs(n) >= 1000:
        return f"{sign}${abs(n):,.0f}"
    return f"{sign}${abs(n):,.2f}"


def side_by_side(left, right):
    """Merge two column lists with │ divider."""
    lines = []
    for i in range(max(len(left), len(right))):
        l = left[i] if i < len(left) else ""
        r = right[i] if i < len(right) else ""
        lines.append(f"  {l:<{COL_W}}│ {r}")
    return "\n".join(lines)


# ── Compact positions ────────────────────────────────────────────────

def _fmt_price(p):
    """Format price compactly based on magnitude."""
    if p < 1:
        return f"{p:.5f}"
    if p < 100:
        return f"{p:.2f}"
    return f"{p:.2f}"


def _compact_positions(state, label):
    """One-line-per-position format."""
    if state is None:
        return ""
    open_pos = state.get("open", [])
    if not open_pos:
        return f"### {label}\nNone\n"

    lines = [f"### {label}"]
    for p in open_pos:
        sym = p.get("symbol", "?")
        d = p.get("direction", "?")[:5]
        entry = p.get("entry", 0)
        cur = p.get("current_price", entry)
        pnl = p.get("unrealized_pnl", 0)
        sl = p.get("stop_loss", 0)
        tp = p.get("take_profit", 0)
        pnl_s = f"+${pnl:,.0f}" if pnl >= 0 else f"-${abs(pnl):,.0f}"
        arrow = f"{_fmt_price(entry)}→{_fmt_price(cur)}"
        lines.append(
            f"  {sym:<7} {d:<5} {arrow:<20} {pnl_s:>7}"
            f"  SL:{_fmt_price(sl)} TP:{_fmt_price(tp)}"
        )
    return "\n".join(lines)


# ── Compact closes ───────────────────────────────────────────────────

def _compact_closes(state, label):
    """Last 5 closed trades, compact format."""
    if state is None:
        return ""
    closed = state.get("closed", [])
    if not closed:
        return f"{label}: none"

    lines = [f"{label}:"]
    for t in closed[-5:]:
        tid = t.get("id", "?")
        sym = t.get("symbol", "?")
        d = t.get("direction", "?")[:5]
        pnl = t.get("pnl_dollars", 0)
        reason = t.get("close_reason", "?")
        dt = t.get("date_closed", "?")
        # Shorten date to MM-DD
        if len(dt) >= 10:
            dt = dt[5:]
        pnl_s = f"+${pnl:,.0f}" if pnl >= 0 else f"-${abs(pnl):,.0f}"
        lines.append(f"  {tid:<5} {sym:<7} {d:<5} {pnl_s:>8}  {reason:<14} {dt}")
    return "\n".join(lines)


# ── Compact footer sections ──────────────────────────────────────────

def _education_line(curriculum_text):
    if curriculum_text is None:
        return "Education: N/A"
    done = total = 0
    current_section = None
    for line in curriculum_text.split("\n"):
        m = re.match(r'\|\s*(\d+)\s*\|([^|]+)\|([^|]+)\|([^|]+)\|\s*(\w[\w-]*)\s*\|', line)
        if m:
            total += 1
            if m.group(5).strip() == "done":
                done += 1
                current_section = m.group(2).strip()
    pct = done / total * 100 if total > 0 else 0
    sec = f" — {current_section}" if current_section else ""
    return f"Education: {done}/{total} ({pct:.0f}%){sec}"


def _gates_line(state, lessons, curriculum_text, watchlist):
    passed = 0
    blocker = None

    # Gate 1: 50+ trades with positive expectancy
    if lessons:
        count = lessons.get("trade_count", 0)
        total_pnl = sum(d.get("avg_pnl", 0) * d.get("count", 0)
                        for d in lessons.get("by_signal_type", {}).values())
        avg_pnl = total_pnl / count if count > 0 else 0
        if count >= 50 and avg_pnl > 0:
            passed += 1
        else:
            blocker = f"need 50+ trades w/ positive exp ({count} trades)"
    else:
        closed_count = len(state.get("closed", [])) if state else 0
        blocker = f"need 50+ trades ({closed_count} closed)"

    # Gate 2: Correlation guard
    try:
        td_path = os.path.join(REPO, "toolkit", "trading", "market_trade_decision.py")
        with open(td_path) as f:
            if "correlation" in f.read().lower():
                passed += 1
            elif not blocker:
                blocker = "need correlation guard"
    except FileNotFoundError:
        if not blocker:
            blocker = "need correlation guard"

    # Gate 3: Education > 50%
    done = total = 0
    if curriculum_text:
        for line in curriculum_text.split("\n"):
            m = re.match(r'\|\s*(\d+)\s*\|([^|]+)\|([^|]+)\|([^|]+)\|\s*(\w[\w-]*)\s*\|', line)
            if m:
                total += 1
                if m.group(5).strip() == "done":
                    done += 1
    if total > 0 and done / total >= 0.5:
        passed += 1
    elif not blocker:
        blocker = "need education > 50%"

    # Gate 4: Spread/slippage
    rules = watchlist.get("rules", {}) if watchlist else {}
    if rules.get("spread") and rules.get("slippage"):
        passed += 1
    elif not blocker:
        blocker = "need spread/slippage modeling"

    suffix = f" ({blocker})" if blocker else ""
    return f"Gates: {passed}/4 passed{suffix}"


def _backtest_line(report, fractal_report):
    parts = []
    for r, name in [(report, "Main"), (fractal_report, "Fractal")]:
        if r is None:
            continue
        m = r.get("metrics", {})
        wr = m.get("win_rate", 0) * 100
        sharpe = m.get("sharpe_ratio", 0)
        parts.append(f"{name} {wr:.0f}%WR {sharpe:.2f}S")
    if not parts:
        return "Backtest: N/A"
    return f"Backtest: {' │ '.join(parts)}"


# ── Main ─────────────────────────────────────────────────────────────

def main():
    state = load_json(os.path.join(PRIVATE, "paper-state.json"))
    fractal_state = load_json(os.path.join(PRIVATE, "fractal-state.json"))
    lessons = load_json(os.path.join(PRIVATE, "trade-lessons.json"))
    watchlist = load_json(os.path.join(CONFIG, "watchlist.json"))
    curriculum = load_text(os.path.join(EDU, "curriculum-progress.md"))
    report = load_json(os.path.join(PRIVATE, "validation", "validation-report.json"))
    fractal_report = load_json(os.path.join(PRIVATE, "validation", "validation-report-fractal.json"))

    today = datetime.now(ET).date().isoformat()
    print(f"# Trading Status — {today}")
    print()

    # Side-by-side fund summary
    main_stats = _fund_stats(state, lessons)
    fractal_stats = _fund_stats(fractal_state)
    left = _fund_column("Main Fund (Trend/SMA)", main_stats)
    right = _fund_column("Fractal Fund (Fractal Breakout)", fractal_stats)
    print(side_by_side(left, right))
    print(f"  {'─' * COL_W}┴{'─' * COL_W}")
    print()

    # Open positions (stacked — variable length)
    main_pos = _compact_positions(state, "Open — Main")
    frac_pos = _compact_positions(fractal_state, "Open — Fractal")
    if main_pos:
        print(main_pos)
    if frac_pos:
        if main_pos:
            print()
        print(frac_pos)
    print()

    # Recent closes
    print("### Recent Closes")
    main_closes = _compact_closes(state, "Main")
    frac_closes = _compact_closes(fractal_state, "Fractal")
    if main_closes:
        print(main_closes)
    if frac_closes:
        print(frac_closes)
    print()

    # Footer one-liners
    print(_education_line(curriculum))
    print(_gates_line(state, lessons, curriculum, watchlist))
    print(_backtest_line(report, fractal_report))


if __name__ == "__main__":
    main()
