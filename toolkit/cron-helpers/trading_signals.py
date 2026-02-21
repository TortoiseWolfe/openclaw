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
import statistics

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


def compute_atr(candles, period=14):
    """Average True Range over period."""
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(-period, 0):
        c = candles[i]
        cp = candles[i - 1]["c"]
        tr = max(c["h"] - c["l"], abs(c["h"] - cp), abs(c["l"] - cp))
        trs.append(tr)
    return statistics.mean(trs) if trs else None


def compute_adx(candles, period=14):
    """Average Directional Index — trend strength (0-100).

    ADX > 25 = trending. ADX < 20 = ranging/choppy.
    Uses Wilder smoothing (pure stdlib).
    """
    if len(candles) < period * 2 + 1:
        return None

    tr_list, plus_dm_list, minus_dm_list = [], [], []
    for i in range(1, len(candles)):
        c, p = candles[i], candles[i - 1]
        tr = max(c["h"] - c["l"], abs(c["h"] - p["c"]), abs(c["l"] - p["c"]))
        up_move = c["h"] - p["h"]
        down_move = p["l"] - c["l"]
        plus_dm = up_move if up_move > down_move and up_move > 0 else 0
        minus_dm = down_move if down_move > up_move and down_move > 0 else 0
        tr_list.append(tr)
        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)

    if len(tr_list) < period * 2:
        return None

    def wilder_smooth(values, n):
        result = [sum(values[:n]) / n]
        for v in values[n:]:
            result.append((result[-1] * (n - 1) + v) / n)
        return result

    smooth_tr = wilder_smooth(tr_list, period)
    smooth_plus = wilder_smooth(plus_dm_list, period)
    smooth_minus = wilder_smooth(minus_dm_list, period)

    dx_list = []
    min_len = min(len(smooth_tr), len(smooth_plus), len(smooth_minus))
    for i in range(min_len):
        if smooth_tr[i] == 0:
            continue
        plus_di = 100 * smooth_plus[i] / smooth_tr[i]
        minus_di = 100 * smooth_minus[i] / smooth_tr[i]
        di_sum = plus_di + minus_di
        if di_sum == 0:
            continue
        dx_list.append(100 * abs(plus_di - minus_di) / di_sum)

    if len(dx_list) < period:
        return None
    adx_values = wilder_smooth(dx_list, period)
    return adx_values[-1] if adx_values else None


def classify_regime(candles, lookback=60):
    """Classify market regime: bull/bear × high/low vol, or ranging."""
    if len(candles) < max(lookback, 21):
        return "unknown"
    recent = candles[-lookback:]
    sma_start = statistics.mean([c["c"] for c in recent[:20]])
    sma_end = statistics.mean([c["c"] for c in recent[-20:]])
    sma_change = (sma_end - sma_start) / sma_start if sma_start > 0 else 0
    atr = compute_atr(candles, 20)
    sma = statistics.mean([c["c"] for c in candles[-20:]])
    vol_ratio = atr / sma if sma > 0 and atr else 0
    high_vol = vol_ratio > 0.015
    if abs(sma_change) < 0.02:
        return "ranging"
    elif sma_change > 0:
        return "bull_high_vol" if high_vol else "bull_low_vol"
    else:
        return "bear_high_vol" if high_vol else "bear_low_vol"


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

    # Configurable trend threshold (default 3 for backwards compat)
    min_tc = rules.get("min_trend_count", 3)
    if hh >= min_tc and hl >= min_tc:
        trend = "uptrend"
    elif lh >= min_tc and ll >= min_tc:
        trend = "downtrend"
    else:
        trend = "ranging"

    # ── ATR volatility filter (skip dead markets) ────────────────
    atr_cfg = rules.get("atr_filter", {})
    atr_val = compute_atr(candles, period=atr_cfg.get("period", 14))
    if atr_cfg.get("enabled", False) and atr_val and len(candles) >= 21:
        sma_20 = compute_sma(candles, 20)
        if sma_20 and sma_20 > 0:
            atr_pct = atr_val / sma_20
            if atr_pct < atr_cfg.get("min_atr_pct", 0.005):
                return {
                    "asset_class": asset_class, "symbol": symbol,
                    "trend": "low_volatility", "support": 0, "resistance": 0,
                    "last_close": last["c"], "last_high": last["h"],
                    "last_low": last["l"], "last_date": last["date"],
                    "pattern": None, "signal": None, "sma_signal": None,
                    "hh": hh, "hl": hl, "lh": lh, "ll": ll,
                }

    # ── ADX trend strength filter ───────────────────────────────
    adx_cfg = rules.get("adx_filter", {})
    if adx_cfg.get("enabled", False) and trend in ("uptrend", "downtrend"):
        adx_val = compute_adx(candles, period=adx_cfg.get("period", 14))
        if adx_val is not None and adx_val < adx_cfg.get("min_adx", 25):
            trend = "weak_trend"  # demote — don't enter

    # ── Regime detection ────────────────────────────────────────
    regime = classify_regime(candles) if len(candles) >= 60 else "unknown"
    regime_cfg = rules.get("regime_filter", {})
    if regime_cfg.get("enabled", False):
        skip_regimes = regime_cfg.get("skip_regimes", [])
        if regime in skip_regimes:
            return {
                "asset_class": asset_class, "symbol": symbol,
                "trend": trend, "regime": regime,
                "support": 0, "resistance": 0,
                "last_close": last["c"], "last_high": last["h"],
                "last_low": last["l"], "last_date": last["date"],
                "pattern": None, "signal": None, "sma_signal": None,
                "hh": hh, "hl": hl, "lh": lh, "ll": ll,
            }

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
    elif rules.get("ranging_entries", True):
        # Ranging market signals — gated by config flag
        if sma_signal and "bullish" in sma_signal:
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

    # ── SMA confirmation filter (veto trades against medium-term trend) ──
    if direction and rules.get("sma_confirmation", False) and sma_signal:
        if direction == "LONG" and "bearish" in sma_signal:
            direction = None
            reason_parts = []
        elif direction == "SHORT" and "bullish" in sma_signal:
            direction = None
            reason_parts = []

    if direction:
        if pattern and pattern not in " ".join(reason_parts):
            reason_parts.append(pattern)
        if sma_signal and sma_signal not in " ".join(reason_parts):
            reason_parts.append(sma_signal)

        sr_label = "S/R" if "Support and Resistance Levels" in edu_sections else "range"

        # ── Stop placement: ATR-based or S/R-based ──────────────
        atr_stops_cfg = rules.get("atr_stops", {})
        use_atr_stops = atr_stops_cfg.get("enabled", False) and atr_val and atr_val > 0

        if direction == "LONG":
            reason_parts.append(f"{sr_label}: {support:.5f}")
            if use_atr_stops:
                atr_mult = atr_stops_cfg.get("multiplier", 1.5)
                sl = last["c"] - atr_val * atr_mult
                stop_dist = last["c"] - sl
            else:
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
            if use_atr_stops:
                atr_mult = atr_stops_cfg.get("multiplier", 1.5)
                sl = last["c"] + atr_val * atr_mult
                stop_dist = sl - last["c"]
            else:
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
        "regime": regime,
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
