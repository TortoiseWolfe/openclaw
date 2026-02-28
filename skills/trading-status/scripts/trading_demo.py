#!/usr/bin/env python3
"""Trading system demo walkthrough — architecture, pipeline, and live data.

Designed for showing interns and peers how the system works. Uses ASCII art,
real data snippets, and plain-language annotations so someone unfamiliar
with the system can follow along.

All file reads are best-effort — missing files produce helpful notes, not crashes.
"""

import json
import logging
import os
import re
import sys
from datetime import date
from glob import glob

logger = logging.getLogger(__name__)


def find_repo_root():
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(10):
        if os.path.isdir(os.path.join(d, "trading-data")):
            return d
        d = os.path.dirname(d)
    return None


REPO = find_repo_root()
if REPO is None:
    logger.error("ERROR: Could not find repo root")
    sys.exit(1)

DATA = os.path.join(REPO, "trading-data")
PRIVATE = os.path.join(DATA, "private")
CONFIG = os.path.join(DATA, "config")
EDU = os.path.join(DATA, "education")


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


def print_header():
    today = date.today().isoformat()
    logger.info(f"""
================================================================================
  MOLTBOT TRADING SYSTEM — WALKTHROUGH
  {today}
================================================================================

  A fully autonomous paper trading pipeline running inside Docker.
  No UI — everything is cron jobs, JSON files, and markdown output.
  This walkthrough shows how all the pieces fit together.
""")


def print_infrastructure():
    logger.info("""
== 1. INFRASTRUCTURE ============================================================

  Everything runs in Docker on WSL2 (Debian). Four services:

  ┌─────────────────────────────────────────────────────────────────────┐
  │  WSL2 Host (Debian)                                                 │
  │                                                                     │
  │  ┌──────────┐   ┌──────────────┐   ┌────────────────────────────┐   │
  │  │  Ollama  │   │ MCP Gateway  │   │   Moltbot Gateway          │   │
  │  │          │   │              │   │                            │   │
  │  │ qwen3:8b │◄──│ 139 tools    │◄──│ Cron scheduler             │   │
  │  │ (local   │   │ (LinkedIn,   │   │ Trade engine               │   │
  │  │  LLM)    │   │  Gmail,      │   │ Agent sessions             │   │
  │  │          │   │  Playwright, │   │                            │   │
  │  │ RTX 3060 │   │  GitHub,     │   │ Python scripts run here    │   │
  │  │ Ti 8GB   │   │  YouTube...) │   │ via: docker compose exec   │   │
  │  └──────────┘   └──────────────┘   └─────────────┬──────────────┘   │
  │                                                  │                  │
  │                                   ┌──────────────▼──────────────┐   │
  │                                   │     trading-data/           │   │
  │                                   │     (bind-mounted volume)   │   │
  │                                   │     JSON + Markdown files   │   │
  │                                   └─────────────────────────────┘   │
  └─────────────────────────────────────────────────────────────────────┘

  Key: The gateway container runs all Python cron jobs. Ollama provides
  local AI inference. MCP Gateway aggregates 139 external tool APIs.
  All trading data lives in JSON/markdown files on the host filesystem.
""")


def print_watchlist():
    wl = load_json(os.path.join(CONFIG, "watchlist.json"))
    if wl is None:
        logger.info("  (watchlist.json not found)\n")
        return

    forex = [a["symbol"] for a in wl.get("forex", [])]
    stocks = [a["symbol"] for a in wl.get("stocks", [])]
    crypto = [a["symbol"] for a in wl.get("crypto", [])]
    total = len(forex) + len(stocks) + len(crypto)

    rules = wl.get("rules", {})
    risk = rules.get("max_risk", 0)
    rr = rules.get("rr_ratio", 0)
    max_pos = rules.get("max_positions", {}).get("global", 0)

    logger.info(f"""
== 2. WHAT WE'RE TRACKING ======================================================

  {total} assets across 3 classes, checked every weekday at 9:00 AM ET.

  Forex  ({len(forex)}):  {', '.join(forex)}
  Stocks ({len(stocks)}): {', '.join(stocks[:10])}
                  {', '.join(stocks[10:])}
  Crypto ({len(crypto)}):  {', '.join(crypto)}

  Rules:
    Risk per trade:   {risk*100:.0f}% of balance
    Reward:Risk:      {rr}:1  (need >{1/(1+rr)*100:.0f}% win rate to break even)
    Max positions:    {max_pos} at a time
    Spread modeled:   {'Yes' if rules.get('spread') else 'No'}
    Slippage modeled: {'Yes' if rules.get('slippage') else 'No'}
""")


def print_pipeline():
    logger.info("""
== 3. DAILY PIPELINE (Mon-Fri) =================================================

  Every weekday, 6 cron jobs run in sequence:

  8:30 AM ── Market Data Pull ─────────────────────────────────────────
  │          Fetch daily candles for all 33 assets
  │          Sources: Alpha Vantage (forex/crypto), Yahoo Finance (stocks)
  │""")

    # Show sample candle data
    sample_file = os.path.join(DATA, "data", "forex", "EURUSD-daily.json")
    sample = load_json(sample_file)
    if sample and sample.get("candles"):
        last = sample["candles"][-1]
        updated = sample.get("lastUpdated", "?")[:10]
        logger.info(f"  │   Example: EURUSD latest candle ({last['date']}):")
        logger.info(f"  │     Open: {last['o']:.5f}  High: {last['h']:.5f}  "
              f"Low: {last['l']:.5f}  Close: {last['c']:.5f}")
        logger.info(f"  │     (data as of {updated})")
    else:
        logger.info("  │   (no candle data collected yet)")

    logger.info("""  │
  8:35 AM ── Supplementary Data Pull ──────────────────────────────────
  │          Rotating schedule: earnings dates, company overviews,
  │          intraday forex. 9 API calls/day on a weekday rotation.
  │""")

    # Check for earnings data
    earnings_files = glob(os.path.join(DATA, "data", "stocks", "*-earnings.json"))
    overview_files = glob(os.path.join(DATA, "data", "stocks", "*-overview.json"))
    if earnings_files:
        sample_e = load_json(earnings_files[0])
        if sample_e:
            sym = os.path.basename(earnings_files[0]).replace("-earnings.json", "")
            nxt = sample_e.get("next_earnings_date", "unknown")
            logger.info(f"  │   Example: {sym} next earnings: {nxt}")
    if not earnings_files and not overview_files:
        logger.info("  │   (no supplementary data collected yet)")

    logger.info("""  │
  8:45 AM ── News Sentiment ───────────────────────────────────────────
  │          Alpha Vantage NEWS_SENTIMENT API (3 batched calls)
  │          Scores: -1.0 (bearish) to +1.0 (bullish)
  │""")

    # Check for sentiment data
    today_str = date.today().isoformat()
    sent = load_json(os.path.join(DATA, "data", "news", f"sentiment-{today_str}.json"))
    if sent and sent.get("market_summary"):
        ms = sent["market_summary"]
        logger.info(f"  │   Today's market: {ms.get('overall_label', '?')} "
              f"(score: {ms.get('overall_sentiment', 0):.3f})")
        if ms.get("most_bullish"):
            logger.info(f"  │   Most bullish: {ms['most_bullish']}  |  "
                  f"Most bearish: {ms.get('most_bearish', '?')}")
    else:
        logger.info("  │   (no sentiment data for today)")

    logger.info("""  │
  9:00 AM ── Trade Decision (THE ORCHESTRATOR) ────────────────────────
  │          1. Check stop-loss / take-profit on open positions
  │          2. Friday: close all forex (weekend gap risk)
  │          3. Analyze all 33 assets for trade signals
  │          4. Open new trades (up to position limit)
  │          5. Apply slippage, spread, confidence multipliers
  │""")

    state = load_json(os.path.join(PRIVATE, "paper-state.json"))
    if state:
        bal = state.get("balance", 0)
        n_open = len(state.get("open", []))
        n_closed = len(state.get("closed", []))
        logger.info(f"  │   Current: ${bal:,.2f} balance, "
              f"{n_open} open, {n_closed} closed all-time")
        for p in state.get("open", []):
            pnl = p.get("unrealized_pnl", 0)
            logger.info(f"  │     {p['symbol']:8s} {p['direction']:5s} "
                  f"entry: {p['entry']:.5f}  P&L: ${pnl:+,.2f}")
    else:
        logger.info("  │   (no trading state yet)")

    logger.info("""  │
  9:05 AM ── Fractal Fund ───────────────────────────────────────────
  │          Independent paper fund using Williams Fractal breakouts.
  │          Separate balance, positions, and trade IDs (F-prefix).
  │          Same stop/close logic, different entry signals.
  │""")

    fractal = load_json(os.path.join(PRIVATE, "fractal-state.json"))
    if fractal:
        fbal = fractal.get("balance", 0)
        fn_open = len(fractal.get("open", []))
        fn_closed = len(fractal.get("closed", []))
        logger.info(f"  │   Current: ${fbal:,.2f} balance, "
              f"{fn_open} open, {fn_closed} closed all-time")
        for p in fractal.get("open", []):
            pnl = p.get("unrealized_pnl", 0)
            logger.info(f"  │     {p['symbol']:8s} {p['direction']:5s} "
                  f"entry: {p['entry']:.5f}  P&L: ${pnl:+,.2f}")
    else:
        logger.info("  │   (no fractal fund state yet)")

    logger.info("""  │
  9:20 AM ── Post-Mortem Analysis ─────────────────────────────────────
             Analyze every closed trade: what worked, what didn't.
             Output feeds back into tomorrow's trade decisions.
""")

    lessons = load_json(os.path.join(PRIVATE, "trade-lessons.json"))
    if lessons and lessons.get("trade_count", 0) > 0:
        tc = lessons["trade_count"]
        for st, data in lessons.get("by_signal_type", {}).items():
            wr = data.get("win_rate", 0) * 100
            cm = data.get("confidence_multiplier", 1.0)
            logger.info(f"             Signal '{st}': {data.get('count', 0)} trades, "
                  f"{wr:.0f}% win rate -> {cm:.2f}x sizing multiplier")
    else:
        logger.info("             (no post-mortem data yet — need closed trades first)")
    logger.info("")


def print_feedback_loop():
    logger.info("""
== 4. FEEDBACK LOOP ============================================================

  The system learns from its own trades. Every day at 9:20 AM, the
  post-mortem analyzes closed trades and writes a "lessons" file.
  The next morning's trade decision reads those lessons.

  ┌─────────────────────┐     ┌─────────────────────┐
  │  Trade Decision     │     │  Post-Mortem        │
  │  (9:00 AM)          │     │  (9:20 AM)          │
  │                     │     │                     │
  │  Reads lessons ->   │     │  Analyzes trades -> │
  │  Adjusts sizing     │     │  Writes lessons     │
  │  Skips bad symbols  │     │  Flags losers       │
  └─────────┬───────────┘     └─────────┬───────────┘
            │                           │
            │   trade-lessons.json      │
            │◄──────────────────────────┘
            │   (confidence multipliers,
            │    skip flags, stop analysis)
            ▼

  Example: If "trend" signals only win 20% of the time, the system
  automatically reduces position size for trend trades (0.5x).
  If a symbol loses 5+ trades in a row, it gets skipped entirely.
""")


def print_education():
    curriculum = load_text(os.path.join(EDU, "curriculum-progress.md"))
    if curriculum is None:
        logger.info("== 5. EDUCATION PIPELINE ========================================")
        logger.info("  (curriculum-progress.md not found)\n")
        return

    done = 0
    total = 0
    current_section = None
    for line in curriculum.split("\n"):
        m = re.match(r'\|\s*(\d+)\s*\|([^|]+)\|([^|]+)\|([^|]+)\|\s*(\w[\w-]*)\s*\|', line)
        if m:
            total += 1
            if m.group(5).strip() == "done":
                done += 1
                current_section = m.group(2).strip()

    pct = done / total * 100 if total > 0 else 0
    bar_len = 40
    filled = int(bar_len * done / total) if total > 0 else 0
    bar = "█" * filled + "░" * (bar_len - filled)

    logger.info(f"""
== 5. EDUCATION PIPELINE =======================================================

  The bot studies BabyPips School of Pipsology autonomously.
  Cron jobs fetch and summarize lessons at 4 PM, 8 PM, and overnight.

  Progress: [{bar}] {pct:.0f}%
            {done} / {total} lessons completed

  Current section: {current_section or 'N/A'}

  As lessons are completed, new trading capabilities unlock:
    "Japanese Candlesticks" -> pattern-based signals
    "Moving Averages"       -> SMA crossover signals
    "Support & Resistance"  -> S/R-based stop placement
    "Fundamental Analysis"  -> news sentiment filtering
""")


def print_backtest():
    report = load_json(os.path.join(PRIVATE, "validation", "validation-report.json"))
    if report is None:
        logger.info("== 6. BACKTEST VALIDATION ======================================")
        logger.info("  (validation-report.json not found)\n")
        return

    m = report.get("metrics", {})
    cfg = report.get("config", {})
    mc = report.get("monte_carlo", {})

    wr = m.get("win_rate", 0) * 100
    sharpe = m.get("sharpe_ratio", 0)
    pf = m.get("profit_factor", 0)
    dd = m.get("max_drawdown_pct", 0) * 100
    final = m.get("final_balance", 0)
    ruin = mc.get("ruin_pct", 0) * 100

    logger.info(f"""
== 6. BACKTEST VALIDATION ======================================================

  Before trusting real money, the signal logic is replayed over
  10 years of historical data ({cfg.get('start', '?')} to {cfg.get('end', '?')}).

  {m.get('total_trades', '?')} simulated trades across {cfg.get('symbol_count', '?')} assets:

    Win rate:       {wr:.1f}%    (need >25% at 3:1 RR to break even)
    Sharpe ratio:   {sharpe:.4f}  (want >1.0 for real money)
    Profit factor:  {pf:.3f}   (want >1.3 — means $1.30 gained per $1 lost)
    Max drawdown:   {dd:.1f}%    (want <30% — currently too high)
    Final balance:  ${final:,.2f}  (started at $10,000)
    Monte Carlo:    {ruin:.0f}% ruin probability  (want <5%)

  Verdict: NOT ready for real money yet. The system needs more
  signal refinement, correlation guards, and education unlocks
  before the numbers improve enough.
""")


def print_current_status():
    state = load_json(os.path.join(PRIVATE, "paper-state.json"))
    if state is None:
        logger.info("== 7. CURRENT STATUS ===========================================")
        logger.info("  (no trading state)\n")
        return

    bal = state.get("balance", 0)
    peak = state.get("peak_balance", 10000)
    dd = (peak - bal) / peak * 100 if peak > 0 else 0
    n_open = len(state.get("open", []))
    n_closed = len(state.get("closed", []))
    unrealized = sum(p.get("unrealized_pnl", 0) for p in state.get("open", []))

    logger.info(f"""
== 7. CURRENT STATUS ===========================================================

  Paper account (play money — $10,000 starting balance):

    Balance:     ${bal:,.2f}
    Unrealized:  ${unrealized:+,.2f}    (from {n_open} open positions)
    Peak:        ${peak:,.2f}
    Drawdown:    {dd:.1f}%
    Total trades:{n_closed} closed all-time

  This is intentionally aggressive — we learn more from taking trades
  and analyzing the results than from sitting on cash. Position sizing,
  signal filtering, and stop placement improve automatically as the
  post-mortem feedback loop accumulates data.
""")

    fractal = load_json(os.path.join(PRIVATE, "fractal-state.json"))
    if fractal:
        fbal = fractal.get("balance", 0)
        fpeak = fractal.get("peak_balance", 10000)
        fdd = (fpeak - fbal) / fpeak * 100 if fpeak > 0 else 0
        fn_open = len(fractal.get("open", []))
        fn_closed = len(fractal.get("closed", []))
        funrealized = sum(p.get("unrealized_pnl", 0) for p in fractal.get("open", []))

        logger.info(f"""  Fractal fund (Williams Fractal breakouts — separate $10,000 seed):

    Balance:     ${fbal:,.2f}
    Unrealized:  ${funrealized:+,.2f}    (from {fn_open} open positions)
    Peak:        ${fpeak:,.2f}
    Drawdown:    {fdd:.1f}%
    Total trades:{fn_closed} closed all-time
""")


def print_whats_next():
    logger.info("""
== WHAT'S NEXT =================================================================

  Upcoming improvements (in priority order):

  1. Hit 50+ trades -> evaluate position scaling
  2. Eventually: real money (needs 3+ months profitable paper trading)

  Recently completed:
    + Fractal paper fund — independent Williams Fractal breakout strategy
      running side by side with the main trend/SMA fund for comparison
    + Correlation guard — prevents doubling up on correlated positions
      (forex: max 1 position per currency side, stocks: max 1 per sector)
    + News sentiment now dampens/vetoes trades that disagree with market mood
    + Education gating is real — patterns gated by Japanese Candlesticks,
      range position by Support & Resistance, SMA by Moving Averages

  Commands:
    /trading-status  — Quick dashboard (balance, positions, gates)
    /trading-demo    — This walkthrough

================================================================================
""")


def main():
    print_header()
    print_infrastructure()
    print_watchlist()
    print_pipeline()
    print_feedback_loop()
    print_education()
    print_backtest()
    print_current_status()
    print_whats_next()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
