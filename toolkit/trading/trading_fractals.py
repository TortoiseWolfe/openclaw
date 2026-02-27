#!/usr/bin/env python3
"""Williams Fractal detection and fractal breakout signal generation.

A Williams Fractal is a 5-candle pattern (window=2):
  - Bearish fractal (resistance): center has highest high, strict > on both sides
  - Bullish fractal (support): center has lowest low, strict < on both sides

Trading signals fire on breakout above bearish fractals (LONG) or
breakdown below bullish fractals (SHORT).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from trading_signals import compute_atr


# ── Fractal Detection ──────────────────────────────────────────────


def detect_fractals(candles, window=2):
    """Detect Williams Fractals in candle data.

    Args:
        candles: list of {date, o, h, l, c} dicts, sorted by date ascending.
        window: candles on each side of center (default 2 = standard Williams).

    Returns:
        list of {date, index, type, price} sorted by date.
        type is "bearish" (resistance) or "bullish" (support).
    """
    if len(candles) < 2 * window + 1:
        return []

    fractals = []
    for i in range(window, len(candles) - window):
        center = candles[i]

        # Bearish fractal: center high is strictly highest
        is_bearish = all(
            center["h"] > candles[i - j]["h"]
            and center["h"] > candles[i + j]["h"]
            for j in range(1, window + 1)
        )
        if is_bearish:
            fractals.append({
                "date": center["date"],
                "index": i,
                "type": "bearish",
                "price": center["h"],
            })

        # Bullish fractal: center low is strictly lowest
        is_bullish = all(
            center["l"] < candles[i - j]["l"]
            and center["l"] < candles[i + j]["l"]
            for j in range(1, window + 1)
        )
        if is_bullish:
            fractals.append({
                "date": center["date"],
                "index": i,
                "type": "bullish",
                "price": center["l"],
            })

    return fractals


# ── Fractal Signal Generation ──────────────────────────────────────


def fractal_signal(candles, rules, handler=None, symbol="", config=None,
                   window=None, lookback_fractals=None, max_fractal_age=20):
    """Generate a trade signal from Williams Fractal breakouts.

    LONG: current close breaks above the most recent bearish fractal (resistance).
    SHORT: current close breaks below the most recent bullish fractal (support).
    Stop loss at the opposing fractal level; ATR fallback if no opposing fractal.

    Args:
        candles: list of {date, o, h, l, c} dicts, sorted ascending.
        rules: dict with rr_ratio, and optional atr_stops, fractal_window,
               fractal_lookback config.
        handler: asset handler (ForexHandler/StockHandler/CryptoHandler) for
                 stop_buffer. Optional.
        symbol: e.g. "EURUSD". Used for handler calls.
        config: asset config from watchlist. Used for handler calls.
        window: fractal detection window (default from rules or 2).
        lookback_fractals: how many recent fractals to consider (default from
                          rules or 3).
        max_fractal_age: ignore fractals older than this many candles.

    Returns:
        signal dict {direction, entry, stop_loss, take_profit, stop_distance,
                     reason} or None.
    """
    if window is None:
        window = rules.get("fractal_window", 2)
    if lookback_fractals is None:
        lookback_fractals = rules.get("fractal_lookback", 3)

    min_candles = 2 * window + max_fractal_age + 1
    if len(candles) < min_candles:
        return None

    fractals = detect_fractals(candles, window=window)
    if not fractals:
        return None

    last = candles[-1]
    last_close = last["c"]
    last_idx = len(candles) - 1

    # Filter out stale fractals
    fresh = [f for f in fractals if last_idx - f["index"] <= max_fractal_age]
    if not fresh:
        return None

    recent_bearish = [f for f in fresh if f["type"] == "bearish"][-lookback_fractals:]
    recent_bullish = [f for f in fresh if f["type"] == "bullish"][-lookback_fractals:]

    nearest_bearish = recent_bearish[-1] if recent_bearish else None
    nearest_bullish = recent_bullish[-1] if recent_bullish else None

    rr = rules.get("rr_ratio", 2.0)
    atr_val = compute_atr(candles, 14)

    direction = None
    reason = None
    sl = None

    # LONG: close breaks above bearish fractal (resistance breakout)
    if nearest_bearish and last_close > nearest_bearish["price"]:
        direction = "LONG"
        reason = (f"fractal breakout above {nearest_bearish['price']:.5f} "
                  f"({nearest_bearish['date']})")
        if nearest_bullish:
            sl = nearest_bullish["price"]
        elif atr_val:
            sl = last_close - atr_val * 1.5
        else:
            return None

    # SHORT: close breaks below bullish fractal (support breakdown)
    elif nearest_bullish and last_close < nearest_bullish["price"]:
        direction = "SHORT"
        reason = (f"fractal breakdown below {nearest_bullish['price']:.5f} "
                  f"({nearest_bullish['date']})")
        if nearest_bearish:
            sl = nearest_bearish["price"]
        elif atr_val:
            sl = last_close + atr_val * 1.5
        else:
            return None

    if direction is None:
        return None

    # ATR stop override
    atr_stops_cfg = rules.get("atr_stops", {})
    if atr_stops_cfg.get("enabled", False) and atr_val and atr_val > 0:
        atr_mult = atr_stops_cfg.get("multiplier", 1.5)
        if direction == "LONG":
            atr_sl = last_close - atr_val * atr_mult
            sl = max(sl, atr_sl)  # tighter of the two
        else:
            atr_sl = last_close + atr_val * atr_mult
            sl = min(sl, atr_sl)

    # Compute distances
    if direction == "LONG":
        stop_dist = last_close - sl
    else:
        stop_dist = sl - last_close

    if stop_dist <= 0:
        return None

    # Take profit
    if direction == "LONG":
        tp = last_close + stop_dist * rr
    else:
        tp = last_close - stop_dist * rr

    return {
        "direction": direction,
        "entry": last_close,
        "stop_loss": sl,
        "take_profit": tp,
        "stop_distance": stop_dist,
        "reason": reason,
    }
