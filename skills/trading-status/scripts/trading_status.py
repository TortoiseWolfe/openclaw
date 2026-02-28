#!/usr/bin/env python3
"""Trading system dashboard — one-shot status summary.

Reads paper-state.json, trade-lessons.json, curriculum-progress.md,
watchlist.json, and validation-report.json to produce a formatted dashboard.

All reads are best-effort — missing files produce "N/A" lines, not crashes.
"""

import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

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


def load_json(path):
    """Load JSON file, return None if missing or invalid."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def load_text(path):
    """Load text file, return None if missing."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


# ── Portfolio Overview ───────────────────────────────────────────────

def section_portfolio(state):
    if state is None:
        return "## Portfolio\nN/A — paper-state.json not found\n"

    balance = state.get("balance", 0)
    peak = state.get("peak_balance", 10000.0)
    dd_pct = (peak - balance) / peak * 100 if peak > 0 else 0
    open_pos = state.get("open", [])
    closed = state.get("closed", [])
    unrealized = sum(p.get("unrealized_pnl", 0) for p in open_pos)
    equity = balance + unrealized

    lines = [
        "## Portfolio Overview",
        f"Balance:      ${balance:,.2f}",
        f"Equity:       ${equity:,.2f}  (unrealized: ${unrealized:+,.2f})",
        f"Peak:         ${peak:,.2f}  (drawdown: {dd_pct:.1f}%)",
        f"Positions:    {len(open_pos)} open, {len(closed)} closed",
        "",
    ]
    return "\n".join(lines)


# ── Open Positions ───────────────────────────────────────────────────

def section_positions(state):
    if state is None:
        return ""
    open_pos = state.get("open", [])
    if not open_pos:
        return "## Open Positions\nNone\n"

    lines = ["## Open Positions", ""]
    lines.append(f"{'Symbol':<10} {'Dir':<6} {'Entry':>10} {'Current':>10} {'P&L':>10} {'SL':>10} {'TP':>10}")
    lines.append(f"{'─'*10} {'─'*6} {'─'*10} {'─'*10} {'─'*10} {'─'*10} {'─'*10}")

    for p in open_pos:
        sym = p.get("symbol", "?")
        d = p.get("direction", "?")[:5]
        entry = p.get("entry", 0)
        cur = p.get("current_price", entry)
        pnl = p.get("unrealized_pnl", 0)
        sl = p.get("stop_loss", 0)
        tp = p.get("take_profit", 0)
        # Format prices based on magnitude
        fmt = ".5f" if entry < 10 else ".2f"
        lines.append(
            f"{sym:<10} {d:<6} {entry:>10{fmt}} {cur:>10{fmt}} "
            f"{'${:+,.2f}'.format(pnl):>10} {sl:>10{fmt}} {tp:>12{fmt}}"
        )

    lines.append("")
    return "\n".join(lines)


# ── Fractal Fund ────────────────────────────────────────────────────

def section_fractal(state):
    if state is None:
        return "## Fractal Fund (Williams Fractal Breakout)\nN/A — fractal-state.json not found\n"

    balance = state.get("balance", 0)
    peak = state.get("peak_balance", 10000.0)
    dd_pct = (peak - balance) / peak * 100 if peak > 0 else 0
    open_pos = state.get("open", [])
    closed = state.get("closed", [])
    unrealized = sum(p.get("unrealized_pnl", 0) for p in open_pos)
    equity = balance + unrealized

    lines = [
        "## Fractal Fund (Williams Fractal Breakout)",
        f"Balance:      ${balance:,.2f}",
        f"Equity:       ${equity:,.2f}  (unrealized: ${unrealized:+,.2f})",
        f"Peak:         ${peak:,.2f}  (drawdown: {dd_pct:.1f}%)",
        f"Positions:    {len(open_pos)} open, {len(closed)} closed",
        "",
    ]

    if open_pos:
        lines.append(f"{'Symbol':<10} {'Dir':<6} {'Entry':>10} {'Current':>10} {'P&L':>10} {'SL':>10} {'TP':>10}")
        lines.append(f"{'─'*10} {'─'*6} {'─'*10} {'─'*10} {'─'*10} {'─'*10} {'─'*10}")
        for p in open_pos:
            sym = p.get("symbol", "?")
            d = p.get("direction", "?")[:5]
            entry = p.get("entry", 0)
            cur = p.get("current_price", entry)
            pnl = p.get("unrealized_pnl", 0)
            sl = p.get("stop_loss", 0)
            tp = p.get("take_profit", 0)
            fmt = ".5f" if entry < 10 else ".2f"
            lines.append(
                f"{sym:<10} {d:<6} {entry:>10{fmt}} {cur:>10{fmt}} "
                f"{'${:+,.2f}'.format(pnl):>10} {sl:>10{fmt}} {tp:>12{fmt}}"
            )
        lines.append("")

    if closed:
        recent = closed[-5:]
        lines.append("Recent Closed:")
        lines.append(f"{'ID':<6} {'Symbol':<10} {'Dir':<6} {'P&L':>10} {'Reason':<16} {'Date':<12}")
        lines.append(f"{'─'*6} {'─'*10} {'─'*6} {'─'*10} {'─'*16} {'─'*12}")
        for t in recent:
            tid = t.get("id", "?")
            sym = t.get("symbol", "?")
            d = t.get("direction", "?")[:5]
            pnl = t.get("pnl_dollars", 0)
            reason = t.get("close_reason", "?")[:16]
            dt = t.get("date_closed", "?")
            lines.append(f"{tid:<6} {sym:<10} {d:<6} {'${:+,.2f}'.format(pnl):>10} {reason:<16} {dt:<12}")
        lines.append("")

    return "\n".join(lines)


# ── Recent Closed Trades ────────────────────────────────────────────

def section_closed(state):
    if state is None:
        return ""
    closed = state.get("closed", [])
    if not closed:
        return "## Recent Closed Trades\nNone yet\n"

    recent = closed[-5:]  # last 5
    lines = ["## Recent Closed Trades", ""]
    lines.append(f"{'ID':<6} {'Symbol':<10} {'Dir':<6} {'P&L':>10} {'Reason':<16} {'Date':<12}")
    lines.append(f"{'─'*6} {'─'*10} {'─'*6} {'─'*10} {'─'*16} {'─'*12}")

    for t in recent:
        tid = t.get("id", "?")
        sym = t.get("symbol", "?")
        d = t.get("direction", "?")[:5]
        pnl = t.get("pnl_dollars", 0)
        reason = t.get("close_reason", "?")[:16]
        dt = t.get("date_closed", "?")
        lines.append(f"{tid:<6} {sym:<10} {d:<6} {'${:+,.2f}'.format(pnl):>10} {reason:<16} {dt:<12}")

    lines.append("")
    return "\n".join(lines)


# ── Trade Performance ────────────────────────────────────────────────

def section_performance(lessons):
    if lessons is None:
        return "## Trade Performance\nN/A — trade-lessons.json not found\n"

    count = lessons.get("trade_count", 0)
    if count == 0:
        return "## Trade Performance\nNo closed trades yet\n"

    lines = ["## Trade Performance", ""]

    # Overall stats from by_signal_type
    total_pnl = 0
    total_wins = 0
    total_losses = 0
    for st, data in lessons.get("by_signal_type", {}).items():
        total_wins += data.get("wins", 0)
        total_losses += data.get("losses", 0)
        total_pnl += data.get("avg_pnl", 0) * data.get("count", 0)

    win_rate = total_wins / count * 100 if count > 0 else 0
    avg_pnl = total_pnl / count if count > 0 else 0

    lines.append(f"Trades:    {count}")
    lines.append(f"Win rate:  {win_rate:.0f}%  ({total_wins}W / {total_losses}L)")
    lines.append(f"Avg P&L:   ${avg_pnl:+,.2f}")
    lines.append(f"Total P&L: ${total_pnl:+,.2f}")

    # By signal type
    lines.append("")
    lines.append("By signal type:")
    for st, data in lessons.get("by_signal_type", {}).items():
        wr = data.get("win_rate", 0) * 100
        ap = data.get("avg_pnl", 0)
        n = data.get("count", 0)
        lines.append(f"  {st:<12} {n:>3} trades, {wr:>4.0f}% WR, ${ap:+,.2f} avg")

    # By symbol (show worst performers)
    by_sym = lessons.get("by_symbol", {})
    if by_sym:
        sorted_syms = sorted(by_sym.items(), key=lambda x: x[1].get("avg_pnl", 0))
        skipped = [(s, d) for s, d in sorted_syms if d.get("skip", False)]
        if skipped:
            lines.append("")
            lines.append("Skipped symbols (negative track record):")
            for sym, data in skipped:
                lines.append(f"  {sym}: {data.get('count', 0)} trades, ${data.get('avg_pnl', 0):+,.2f} avg")

    lines.append("")
    return "\n".join(lines)


# ── Education Progress ───────────────────────────────────────────────

def section_education(curriculum_text):
    if curriculum_text is None:
        return "## Education Progress\nN/A — curriculum-progress.md not found\n"

    # Count lessons by parsing the detail table rows
    done = 0
    total = 0
    current_section = None
    for line in curriculum_text.split("\n"):
        # Match lesson rows: | # | Section | Lesson | URL | Status | Date |
        m = re.match(r'\|\s*(\d+)\s*\|([^|]+)\|([^|]+)\|([^|]+)\|\s*(\w[\w-]*)\s*\|', line)
        if m:
            total += 1
            status = m.group(5).strip()
            section = m.group(2).strip()
            if status == "done":
                done += 1
                current_section = section

    pct = done / total * 100 if total > 0 else 0

    lines = [
        "## Education Progress",
        f"Lessons:  {done} / {total}  ({pct:.0f}%)",
    ]
    if current_section:
        lines.append(f"Current:  {current_section}")
    lines.append("")
    return "\n".join(lines)


# ── Position Scaling Gates ───────────────────────────────────────────

def section_gates(state, lessons, curriculum_text, watchlist):
    lines = ["## Position Scaling Gates", ""]

    # Gate 1: 50+ trades with positive expectancy
    closed_count = len(state.get("closed", [])) if state else 0
    if lessons:
        total_pnl = 0
        count = lessons.get("trade_count", 0)
        for data in lessons.get("by_signal_type", {}).values():
            total_pnl += data.get("avg_pnl", 0) * data.get("count", 0)
        avg_pnl = total_pnl / count if count > 0 else 0
        gate1 = count >= 50 and avg_pnl > 0
        lines.append(f"{'PASS' if gate1 else 'FAIL'}  Gate 1: 50+ trades w/ positive expectancy "
                      f"({count} trades, ${avg_pnl:+,.2f} avg)")
    else:
        lines.append(f"FAIL  Gate 1: 50+ trades w/ positive expectancy ({closed_count} trades)")

    # Gate 2: Correlation guard live
    # Check if correlation guard code exists
    gate2 = False
    try:
        td_path = os.path.join(REPO, "toolkit", "cron-helpers", "market_trade_decision.py")
        with open(td_path) as f:
            gate2 = "correlation" in f.read().lower()
    except FileNotFoundError:
        pass
    lines.append(f"{'PASS' if gate2 else 'FAIL'}  Gate 2: Correlation guard implemented")

    # Gate 3: Education > 50%
    done = 0
    total = 0
    if curriculum_text:
        for line in curriculum_text.split("\n"):
            m = re.match(r'\|\s*(\d+)\s*\|([^|]+)\|([^|]+)\|([^|]+)\|\s*(\w[\w-]*)\s*\|', line)
            if m:
                total += 1
                if m.group(5).strip() == "done":
                    done += 1
    pct = done / total * 100 if total > 0 else 0
    gate3 = pct >= 50
    lines.append(f"{'PASS' if gate3 else 'FAIL'}  Gate 3: Education > 50% ({done}/{total}, {pct:.0f}%)")

    # Gate 4: Spread/slippage modeling live
    rules = watchlist.get("rules", {}) if watchlist else {}
    has_spread = bool(rules.get("spread"))
    has_slip = bool(rules.get("slippage"))
    gate4 = has_spread and has_slip
    lines.append(f"{'PASS' if gate4 else 'FAIL'}  Gate 4: Spread/slippage modeling live")

    all_pass = all([
        lessons and lessons.get("trade_count", 0) >= 50 and avg_pnl > 0 if lessons else False,
        gate2, gate3, gate4
    ])
    lines.append("")
    if all_pass:
        lines.append(">>> MILESTONE: Position expansion eligible — review before changing limits")
    else:
        passed = sum([gate1 if lessons else False, gate2, gate3, gate4])
        lines.append(f"Progress: {passed}/4 gates passed")

    lines.append("")
    return "\n".join(lines)


# ── Backtest Snapshot ────────────────────────────────────────────────

def _format_backtest(report, label):
    """Format a single backtest report block."""
    m = report.get("metrics", {})
    cfg = report.get("config", {})
    gen = report.get("generated", "?")

    lines = [
        label,
        f"Period:       {cfg.get('start', '?')} to {cfg.get('end', '?')} ({cfg.get('symbol_count', '?')} symbols)",
        f"Generated:    {gen[:10]}",
        f"Trades:       {m.get('total_trades', '?')}",
        f"Win rate:     {m.get('win_rate', 0)*100:.1f}%",
        f"Sharpe:       {m.get('sharpe_ratio', 0):.4f}",
        f"Profit factor: {m.get('profit_factor', 0):.3f}",
        f"Max drawdown: {m.get('max_drawdown_pct', 0)*100:.1f}%",
        f"Final balance:${m.get('final_balance', 0):,.2f}  (from ${m.get('initial_balance', 0):,.2f})",
        "",
    ]

    mc = report.get("monte_carlo", {})
    if mc:
        lines.append(f"Monte Carlo:  {mc.get('profitable_pct', 0)*100:.0f}% profitable, "
                      f"{mc.get('ruin_pct', 0)*100:.0f}% ruin "
                      f"({mc.get('simulations', 0)} sims)")
        lines.append("")

    return "\n".join(lines)


def section_backtest(report, fractal_report=None):
    if report is None and fractal_report is None:
        return "## Backtest Snapshot\nN/A — no validation reports found\n"

    parts = []
    if report is not None:
        strategy = report.get("strategy", "default")
        label = "## Backtest — Main Fund (Trend/SMA)" if strategy != "fractal" else "## Backtest — Fractal Fund"
        parts.append(_format_backtest(report, label))

    if fractal_report is not None:
        parts.append(_format_backtest(fractal_report, "## Backtest — Fractal Fund"))

    return "\n".join(parts)


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
    print(f"# Trading System Status — {today}")
    print()
    print(section_portfolio(state))
    print(section_positions(state))
    print(section_closed(state))
    print(section_fractal(fractal_state))
    print(section_performance(lessons))
    print(section_education(curriculum))
    print(section_gates(state, lessons, curriculum, watchlist))
    print(section_backtest(report, fractal_report))


if __name__ == "__main__":
    main()
