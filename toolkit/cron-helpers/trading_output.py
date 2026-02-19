#!/usr/bin/env python3
"""Output writers for the paper trading engine.

Generates paper-trades.md, daily analysis markdown, and trade journal
entries from trading state and analysis results.
"""

import glob
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trading_common import (
    atomic_text_write,
    PRIVATE_DIR, PAPER_MD, JOURNAL,
)
from trading_handlers import HANDLERS


def write_paper_md(state, edu_status):
    """Regenerate paper-trades.md from state."""
    lines = [
        "# Paper Trades",
        "",
        "Starting balance: $10,000 (simulated)",
        f"Education: {edu_status}",
        "",
        "## Open Positions",
        "",
        "| ID | Date | Asset | Symbol | Dir | Entry | Stop | TP | Size | Unrealized P&L |",
        "|----|------|-------|--------|-----|-------|------|----|------|----------------|",
    ]
    for p in state["open"]:
        unr = f"${p.get('unrealized_pnl', 0):+.2f}" if "unrealized_pnl" in p else "—"
        lines.append(
            f"| {p['id']} | {p['date_opened']} | {p['asset_class']} | {p['symbol']} "
            f"| {p['direction']} | {p['entry']:.5f} | {p['stop_loss']:.5f} "
            f"| {p['take_profit']:.5f} | {p['size']} | {unr} |"
        )

    lines += [
        "",
        "## Closed Positions",
        "",
        "| ID | Opened | Closed | Asset | Symbol | Dir | Entry | Exit | Size | P&L | Reason |",
        "|----|--------|--------|-------|--------|-----|-------|------|------|-----|--------|",
    ]
    for c in state["closed"]:
        lines.append(
            f"| {c['id']} | {c['date_opened']} | {c['date_closed']} | {c['asset_class']} "
            f"| {c['symbol']} | {c['direction']} | {c['entry']:.5f} | {c['exit']:.5f} "
            f"| {c['size']} | ${c['pnl_dollars']:+.2f} | {c.get('close_reason', '')} |"
        )

    # Statistics
    pnls = [c["pnl_dollars"] for c in state["closed"]]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    n = len(pnls)

    lines += [
        "",
        "## Running Statistics",
        "",
        f"- **Total trades:** {len(state['closed']) + len(state['open'])}",
        f"- **Win rate:** {len(wins)/n*100:.0f}%" if n else "- **Win rate:** N/A",
        f"- **Average win:** ${sum(wins)/len(wins):.2f}" if wins else "- **Average win:** N/A",
        f"- **Average loss:** ${sum(losses)/len(losses):.2f}" if losses else "- **Average loss:** N/A",
        f"- **Best trade:** ${max(pnls):.2f}" if pnls else "- **Best trade:** N/A",
        f"- **Worst trade:** ${min(pnls):.2f}" if pnls else "- **Worst trade:** N/A",
        f"- **Total P&L:** ${sum(pnls):.2f}" if pnls else "- **Total P&L:** N/A",
        f"- **Current balance:** ${state['balance']:,.2f}",
        "",
    ]

    atomic_text_write(PAPER_MD, "\n".join(lines))


def write_daily_analysis(analyses, opened, closed_trades, edu_status, today):
    """Write daily analysis markdown."""
    path = os.path.join(PRIVATE_DIR, f"daily-analysis-{today}.md")

    lines = [f"# Daily Analysis — {today}", "", f"**{edu_status}**", ""]

    for asset_class in ["forex", "stocks", "crypto"]:
        class_analyses = [a for a in analyses if a["asset_class"] == asset_class]
        if not class_analyses:
            continue
        lines.append(f"## {asset_class.upper()}")
        lines.append("")
        for a in class_analyses:
            sig_text = "no signal"
            if a["signal"]:
                sig_text = f"{a['signal']['direction']} — {a['signal']['reason']}"
            lines += [
                f"### {a['symbol']}",
                f"- **Trend**: {a['trend']} (HH:{a['hh']}/9 HL:{a['hl']}/9 LH:{a['lh']}/9 LL:{a['ll']}/9)",
                f"- **Support**: {a['support']:.5f}",
                f"- **Resistance**: {a['resistance']:.5f}",
                f"- **Last close**: {a['last_close']:.5f} ({a['last_date']})",
                f"- **Pattern**: {a['pattern'] or 'none'}",
                f"- **SMA**: {a.get('sma_signal') or 'not yet unlocked'}",
                f"- **Signal**: {sig_text}",
                "",
            ]

    if opened:
        lines += ["## Trades Opened", ""]
        for t in opened:
            handler = HANDLERS[t["asset_class"]]
            sent_mult = t.get("sentiment_multiplier")
            sent_reason = t.get("sentiment_reason", "")
            sent_tag = ""
            if sent_mult is not None and sent_mult < 1.0:
                sent_tag = f" | Sentiment: {sent_mult:.1f}x ({sent_reason})"
            elif sent_mult is not None:
                sent_tag = f" | Sentiment: {sent_reason}"
            lines.append(
                f"- **{t['id']}** {t['asset_class']}/{t['symbol']} {t['direction']} "
                f"@ {t['entry']:.5f} (SL: {t['stop_loss']:.5f}, TP: {t['take_profit']:.5f}, "
                f"{handler.format_size(t['size'])}{sent_tag})"
            )
        lines.append("")

    if closed_trades:
        lines += ["## Trades Closed", ""]
        for c in closed_trades:
            lines.append(
                f"- **{c['id']}** {c['asset_class']}/{c['symbol']} {c['direction']} "
                f"closed @ {c['exit']:.5f} ({c['close_reason']}) — ${c['pnl_dollars']:+.2f}"
            )
        lines.append("")

    # Append news sentiment if available
    try:
        from market_news_sentiment import load_sentiment, format_markdown_section
        sentiment = load_sentiment(today)
        if sentiment:
            lines.extend(format_markdown_section(sentiment))
    except ImportError:
        pass

    # Append supplementary news if available
    try:
        from market_news_supplementary import (
            load_supplementary, format_supplementary_markdown,
        )
        supp = load_supplementary(today)
        if supp:
            lines.extend(format_supplementary_markdown(supp))
    except ImportError:
        pass

    atomic_text_write(path, "\n".join(lines))
    return path


def cleanup_old_analyses(today_date, retain_days=30):
    """Delete daily analysis files older than retain_days."""
    cutoff = today_date - timedelta(days=retain_days)
    pattern = os.path.join(PRIVATE_DIR, "daily-analysis-*.md")
    for fpath in glob.glob(pattern):
        fname = os.path.basename(fpath)
        try:
            file_date = date.fromisoformat(
                fname.replace("daily-analysis-", "").replace(".md", ""))
            if file_date < cutoff:
                os.remove(fpath)
        except (ValueError, OSError):
            pass


def append_journal(analyses, opened, closed_trades, balance, edu_status, today):
    """Append entry to trade journal."""
    n_signals = sum(1 for a in analyses if a["signal"])

    entry_lines = [
        f"### {today} — Automated Analysis",
        f"**{edu_status}**",
        f"**Assets analyzed**: {len(analyses)} (forex/stocks/crypto)",
        f"**Trades opened**: {len(opened)}",
        f"**Trades closed**: {len(closed_trades)}",
        f"**Signals found**: {n_signals}/{len(analyses)}",
        f"**Balance**: ${balance:,.2f}",
    ]

    if opened:
        entry_lines.append("**New positions**:")
        for t in opened:
            entry_lines.append(f"  - {t['id']} {t['asset_class']}/{t['symbol']} {t['direction']} — {t['reason']}")
    if closed_trades:
        entry_lines.append("**Closed positions**:")
        for c in closed_trades:
            entry_lines.append(
                f"  - {c['id']} {c['asset_class']}/{c['symbol']} {c['close_reason']} — ${c['pnl_dollars']:+.2f}"
            )

    trends = {}
    for a in analyses:
        ac = a["asset_class"]
        if ac not in trends:
            trends[ac] = []
        trends[ac].append(f"{a['symbol']}={a['trend']}")
    for ac, items in trends.items():
        entry_lines.append(f"**{ac.capitalize()} trends**: {', '.join(items)}")
    entry_lines.append("")

    # Dedup: don't append if today's entry already exists
    try:
        with open(JOURNAL, encoding="utf-8") as f:
            if f"### {today} — Automated Analysis" in f.read():
                return
    except FileNotFoundError:
        pass

    os.makedirs(os.path.dirname(JOURNAL), exist_ok=True)
    with open(JOURNAL, "a", encoding="utf-8") as f:
        f.write("\n".join(entry_lines) + "\n")
