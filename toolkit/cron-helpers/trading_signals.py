#!/usr/bin/env python3
"""Signal generation and education-aware analysis.

Contains the analyze() function that produces trade signals based on
trend detection, candlestick patterns, and SMA crossovers. Analysis
capabilities unlock progressively as BabyPips sections are completed.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trading_common import CURRICULUM, LESSONS_FILE
from trading_handlers import HANDLERS

LOOKBACK = 5    # candles for analysis (backtest-optimized, was 10)


# ── Education progress ───────────────────────────────────────────────

def load_education_progress():
    """Read curriculum-progress.md and return completed sections as a set.

    Sections map to analysis capabilities:
      - "Japanese Candlesticks"  → candlestick pattern recognition
      - "Fibonacci"              → fib retracement levels
      - "Moving Averages"        → SMA/EMA trend confirmation
      - "Support and Resistance Levels" → weighted S/R zones
      - "Popular Chart Indicators" → RSI, MACD, Bollinger, etc.
      - "Oscillators and Momentum Indicators" → leading/lagging indicators
      - "Important Chart Patterns" → chart pattern recognition
      - "Pivot Points"           → pivot level analysis
      - "Trading Divergences"    → divergence detection
      - "Risk Management"        → tighter position sizing
      - "Position Sizing"        → optimized lot sizing
    """
    try:
        with open(CURRICULUM, encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return set(), 0, 0

    completed_sections = set()
    total_done = 0
    total_lessons = 0
    section_lessons = {}
    section_done = {}

    for line in content.splitlines():
        m = re.match(
            r"^\|\s*\d+\s*\|\s*([^|]+?)\s*\|[^|]*\|[^|]*\|\s*(\w[\w-]*)\s*\|",
            line,
        )
        if m:
            section = m.group(1).strip()
            status = m.group(2).strip()
            total_lessons += 1
            section_lessons[section] = section_lessons.get(section, 0) + 1
            if status == "done":
                total_done += 1
                section_done[section] = section_done.get(section, 0) + 1

    for section, count in section_lessons.items():
        if section_done.get(section, 0) >= count:
            completed_sections.add(section)

    return completed_sections, total_done, total_lessons


def education_summary(completed_sections, total_done, total_lessons):
    """Build a human-readable education status string."""
    pct = (total_done / total_lessons * 100) if total_lessons else 0
    unlocked = []
    if "Japanese Candlesticks" in completed_sections:
        unlocked.append("candlesticks")
    if "Fibonacci" in completed_sections:
        unlocked.append("fibonacci")
    if "Moving Averages" in completed_sections:
        unlocked.append("moving averages")
    if "Support and Resistance Levels" in completed_sections:
        unlocked.append("S/R weighting")
    if "Popular Chart Indicators" in completed_sections:
        unlocked.append("indicators")
    if "Important Chart Patterns" in completed_sections:
        unlocked.append("chart patterns")
    if "Risk Management" in completed_sections:
        unlocked.append("risk mgmt")
    if "Position Sizing" in completed_sections:
        unlocked.append("position sizing")

    parts = [f"BabyPips: {total_done}/{total_lessons} ({pct:.0f}%)"]
    if unlocked:
        parts.append(f"Unlocked: {', '.join(unlocked)}")
    else:
        parts.append("Unlocked: basic trend trading (pre-education)")
    return " | ".join(parts)


# ── Lessons feedback (from post-mortem) ──────────────────────────────

def load_lessons():
    """Load trade lessons (feedback from post-mortem). Returns None if no file."""
    try:
        with open(LESSONS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# ── Sentiment multiplier ─────────────────────────────────────────────

def compute_sentiment_multiplier(symbol, direction, sentiment_scores, rules):
    """Compute position-size multiplier based on news sentiment.

    Never boosts above 1.0 — only dampens or vetoes disagreeing trades.

    Returns (multiplier, reason) where:
      multiplier: 0.0 to 1.0
      reason: "agree", "disagree", "strong_disagree", "no_data", or "disabled"
    """
    sent_cfg = rules.get("sentiment", {})
    if not sent_cfg.get("enabled", False):
        return (1.0, "disabled")

    score = sentiment_scores.get(symbol)
    if score is None:
        return (1.0, "no_data")

    # LONG agrees with positive sentiment, SHORT with negative
    agrees = (direction == "LONG" and score >= 0) or \
             (direction == "SHORT" and score <= 0)

    if agrees:
        return (sent_cfg.get("agree_multiplier", 1.0), "agree")

    # Disagreement — check strength
    threshold = sent_cfg.get("strong_disagree_threshold", 0.3)
    if abs(score) >= threshold:
        action = sent_cfg.get("strong_disagree_action", "skip")
        if action == "skip":
            return (0.0, "strong_disagree")
        return (sent_cfg.get("disagree_multiplier", 0.5), "strong_disagree")

    return (sent_cfg.get("disagree_multiplier", 0.5), "disagree")


# ── Analysis (education-aware) ───────────────────────────────────────

def compute_sma(candles, period):
    """Simple moving average of close prices."""
    if len(candles) < period:
        return None
    closes = [c["c"] for c in candles[-period:]]
    return sum(closes) / period


def analyze(asset_class, symbol, config, candles, edu_sections, rules,
            lessons=None):
    """Analyze candles with education-unlocked techniques.

    Base (always): trend direction, support/resistance, position in range.
    Progressive unlocks based on completed BabyPips sections.
    """
    handler = HANDLERS[asset_class]
    recent = candles[-LOOKBACK:]
    if len(recent) < 2:
        return None
    last, prev = recent[-1], recent[-2]

    # ── Core trend detection (Preschool knowledge) ───────────────
    hh = sum(1 for i in range(1, len(recent)) if recent[i]["h"] > recent[i - 1]["h"])
    hl = sum(1 for i in range(1, len(recent)) if recent[i]["l"] > recent[i - 1]["l"])
    lh = sum(1 for i in range(1, len(recent)) if recent[i]["h"] < recent[i - 1]["h"])
    ll = sum(1 for i in range(1, len(recent)) if recent[i]["l"] < recent[i - 1]["l"])

    # Loose trend detection: 3 out of 9 is enough (was 4)
    if hh >= 3 and hl >= 3:
        trend = "uptrend"
    elif lh >= 3 and ll >= 3:
        trend = "downtrend"
    else:
        trend = "ranging"

    support = min(c["l"] for c in recent)
    resistance = max(c["h"] for c in recent)
    rng = resistance - support
    if rng <= 0:
        return None  # all candles identical — no tradable range
    pos_in_range = (last["c"] - support) / rng

    # ── Candlestick patterns (unlocked by Japanese Candlesticks) ──
    pattern = None
    body = abs(last["c"] - last["o"])
    upper_wick = last["h"] - max(last["c"], last["o"])
    lower_wick = min(last["c"], last["o"]) - last["l"]
    prev_body = abs(prev["c"] - prev["o"])

    know_candles = "Japanese Candlesticks" in edu_sections
    bullish_pin = body > 0 and lower_wick > body * 2 and upper_wick < body
    bearish_pin = body > 0 and upper_wick > body * 2 and lower_wick < body
    bullish_engulf = prev["c"] < prev["o"] and last["c"] > last["o"] and body > prev_body
    bearish_engulf = prev["c"] > prev["o"] and last["c"] < last["o"] and body > prev_body

    if bullish_pin:
        pattern = "bullish pin bar" if know_candles else "bullish candle"
    elif bullish_engulf:
        pattern = "bullish engulfing" if know_candles else "bullish candle"
    elif bearish_pin:
        pattern = "bearish pin bar" if know_candles else "bearish candle"
    elif bearish_engulf:
        pattern = "bearish engulfing" if know_candles else "bearish candle"

    # ── Moving averages (unlocked by Moving Averages section) ─────
    sma_signal = None
    if "Moving Averages" in edu_sections and len(candles) >= 20:
        sma_fast = compute_sma(candles, 5)
        sma_slow = compute_sma(candles, 20)
        if sma_fast and sma_slow:
            if sma_fast > sma_slow:
                sma_signal = "SMA5>SMA20 (bullish)"
            else:
                sma_signal = "SMA5<SMA20 (bearish)"

    # ── Build trade signal ────────────────────────────────────────
    signal = None
    buf = handler.stop_buffer(symbol, config, price=last["c"])
    if lessons:
        stop_mult = lessons.get("stop_analysis", {}).get("optimal_stop_multiplier", 1.0)
        buf *= stop_mult
    rr = rules["rr_ratio"]

    bull_pattern = pattern and "bullish" in pattern
    bear_pattern = pattern and "bearish" in pattern

    direction = None
    reason_parts = []

    if trend == "uptrend":
        direction = "LONG"
        reason_parts.append(f"uptrend (HH:{hh}/9)")
    elif trend == "downtrend":
        direction = "SHORT"
        reason_parts.append(f"downtrend (LL:{ll}/9)")
    elif sma_signal and "bullish" in sma_signal:
        direction = "LONG"
        reason_parts.append(sma_signal)
    elif sma_signal and "bearish" in sma_signal:
        direction = "SHORT"
        reason_parts.append(sma_signal)
    elif bull_pattern and know_candles:
        direction = "LONG"
        reason_parts.append(f"ranging + {pattern}")
    elif bear_pattern and know_candles:
        direction = "SHORT"
        reason_parts.append(f"ranging + {pattern}")
    elif pos_in_range < 0.35 and "Support and Resistance Levels" in edu_sections:
        direction = "LONG"
        reason_parts.append(f"ranging, near support ({pos_in_range:.0%})")
    elif pos_in_range > 0.65 and "Support and Resistance Levels" in edu_sections:
        direction = "SHORT"
        reason_parts.append(f"ranging, near resistance ({pos_in_range:.0%})")
    # Dead center in range with no signal — skip (no YOLO trades)

    if direction:
        if pattern and pattern not in " ".join(reason_parts):
            reason_parts.append(pattern)
        if sma_signal and sma_signal not in " ".join(reason_parts):
            reason_parts.append(sma_signal)

        sr_label = "S/R" if "Support and Resistance Levels" in edu_sections else "range"
        if direction == "LONG":
            reason_parts.append(f"{sr_label}: {support:.5f}")
            sl = support - buf
            stop_dist = last["c"] - sl
            if stop_dist <= 0:
                stop_dist = rng * 0.3
                sl = last["c"] - stop_dist
            signal = {
                "direction": "LONG",
                "entry": last["c"],
                "stop_loss": sl,
                "take_profit": last["c"] + stop_dist * rr,
                "stop_distance": stop_dist,
                "reason": ", ".join(reason_parts),
            }
        else:
            reason_parts.append(f"{sr_label}: {resistance:.5f}")
            sl = resistance + buf
            stop_dist = sl - last["c"]
            if stop_dist <= 0:
                stop_dist = rng * 0.3
                sl = last["c"] + stop_dist
            signal = {
                "direction": "SHORT",
                "entry": last["c"],
                "stop_loss": sl,
                "take_profit": last["c"] - stop_dist * rr,
                "stop_distance": stop_dist,
                "reason": ", ".join(reason_parts),
            }

    return {
        "asset_class": asset_class,
        "symbol": symbol,
        "trend": trend,
        "support": support,
        "resistance": resistance,
        "last_close": last["c"],
        "last_high": last["h"],
        "last_low": last["l"],
        "last_date": last["date"],
        "pattern": pattern,
        "signal": signal,
        "sma_signal": sma_signal,
        "hh": hh, "hl": hl, "lh": lh, "ll": ll,
    }
