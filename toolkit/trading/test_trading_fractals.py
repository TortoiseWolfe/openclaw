#!/usr/bin/env python3
"""Tests for Williams Fractal detection and fractal breakout signals."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("TRADING_BASE_DIR",
                      os.path.join(os.path.dirname(__file__), "..", "..", "trading-data"))

from trading_fractals import detect_fractals, fractal_signal
from trading_common import classify_signal


def _candle(date, o, h, l, c):
    return {"date": date, "o": o, "h": h, "l": l, "c": c, "v": 1000}


class TestDetectFractals(unittest.TestCase):

    def test_bearish_fractal_basic(self):
        """Center candle has highest high -> bearish fractal."""
        candles = [
            _candle("2025-01-01", 10, 12, 9, 11),
            _candle("2025-01-02", 11, 13, 10, 12),
            _candle("2025-01-03", 12, 15, 11, 14),  # highest high
            _candle("2025-01-04", 13, 14, 10, 11),
            _candle("2025-01-05", 11, 13, 9, 10),
        ]
        fractals = detect_fractals(candles, window=2)
        bearish = [f for f in fractals if f["type"] == "bearish"]
        self.assertEqual(len(bearish), 1)
        self.assertEqual(bearish[0]["price"], 15)
        self.assertEqual(bearish[0]["index"], 2)

    def test_bullish_fractal_basic(self):
        """Center candle has lowest low -> bullish fractal."""
        candles = [
            _candle("2025-01-01", 10, 12, 8, 11),
            _candle("2025-01-02", 11, 13, 7, 12),
            _candle("2025-01-03", 12, 14, 5, 13),  # lowest low
            _candle("2025-01-04", 13, 15, 6, 14),
            _candle("2025-01-05", 14, 16, 7, 15),
        ]
        fractals = detect_fractals(candles, window=2)
        bullish = [f for f in fractals if f["type"] == "bullish"]
        self.assertEqual(len(bullish), 1)
        self.assertEqual(bullish[0]["price"], 5)
        self.assertEqual(bullish[0]["index"], 2)

    def test_no_fractal_flat(self):
        """Equal highs/lows should not produce fractals (strict inequality)."""
        candles = [_candle(f"2025-01-{i:02d}", 10, 12, 8, 10) for i in range(1, 6)]
        fractals = detect_fractals(candles, window=2)
        self.assertEqual(len(fractals), 0)

    def test_insufficient_candles(self):
        """Fewer than 5 candles returns empty list."""
        candles = [_candle(f"2025-01-{i:02d}", 10, 12, 8, 10) for i in range(1, 4)]
        fractals = detect_fractals(candles, window=2)
        self.assertEqual(len(fractals), 0)

    def test_exactly_five_candles(self):
        """Exactly 5 candles can produce at most 1 fractal at index 2."""
        candles = [
            _candle("2025-01-01", 10, 11, 9, 10),
            _candle("2025-01-02", 10, 12, 9, 11),
            _candle("2025-01-03", 11, 14, 8, 13),  # highest and lowest
            _candle("2025-01-04", 12, 13, 9, 11),
            _candle("2025-01-05", 11, 12, 9, 10),
        ]
        fractals = detect_fractals(candles, window=2)
        # Both bearish (14 > 11,12,13,12) and bullish (8 < 9,9,9,9) possible
        self.assertTrue(len(fractals) >= 1)
        self.assertTrue(all(f["index"] == 2 for f in fractals))

    def test_multiple_fractals_uptrend(self):
        """Uptrend produces fractals at swing points."""
        # Zigzag pattern: up, down, up higher, down, up higher
        candles = [
            _candle("2025-01-01", 10, 11, 9, 10),
            _candle("2025-01-02", 10, 12, 9, 11),
            _candle("2025-01-03", 11, 14, 10, 13),  # bearish fractal
            _candle("2025-01-04", 13, 13, 9, 10),
            _candle("2025-01-05", 10, 11, 7, 9),    # bullish fractal
            _candle("2025-01-06", 9, 10, 8, 10),
            _candle("2025-01-07", 10, 16, 9, 15),   # bearish fractal
            _candle("2025-01-08", 15, 15, 10, 11),
            _candle("2025-01-09", 11, 12, 8, 10),
        ]
        fractals = detect_fractals(candles, window=2)
        bearish = [f for f in fractals if f["type"] == "bearish"]
        bullish = [f for f in fractals if f["type"] == "bullish"]
        self.assertTrue(len(bearish) >= 1)
        self.assertTrue(len(bullish) >= 1)

    def test_window_3(self):
        """Window=3 uses 7-candle pattern."""
        candles = [
            _candle("2025-01-01", 10, 11, 9, 10),
            _candle("2025-01-02", 10, 12, 9, 11),
            _candle("2025-01-03", 11, 13, 9, 12),
            _candle("2025-01-04", 12, 16, 8, 15),  # center: highest high, lowest low
            _candle("2025-01-05", 14, 15, 9, 13),
            _candle("2025-01-06", 13, 14, 9, 12),
            _candle("2025-01-07", 12, 13, 9, 11),
        ]
        fractals = detect_fractals(candles, window=3)
        bearish = [f for f in fractals if f["type"] == "bearish"]
        self.assertEqual(len(bearish), 1)
        self.assertEqual(bearish[0]["price"], 16)
        self.assertEqual(bearish[0]["index"], 3)


class TestFractalSignal(unittest.TestCase):

    def _make_candles_with_fractals(self, close_price):
        """Build 30 candles with clear bearish fractal at high=20 and
        bullish fractal at low=5, then append a final candle with
        the given close_price."""
        candles = []
        # Background candles (indices 0-9)
        for i in range(10):
            candles.append(_candle(f"2025-01-{i+1:02d}", 10, 12, 8, 10))
        # Bullish fractal at index 12 (low=5)
        candles.append(_candle("2025-01-11", 10, 11, 7, 10))
        candles.append(_candle("2025-01-12", 10, 11, 6, 10))
        candles.append(_candle("2025-01-13", 10, 11, 5, 10))  # bullish fractal
        candles.append(_candle("2025-01-14", 10, 11, 6, 10))
        candles.append(_candle("2025-01-15", 10, 11, 7, 10))
        # Bearish fractal at index 17 (high=20)
        candles.append(_candle("2025-01-16", 10, 18, 8, 10))
        candles.append(_candle("2025-01-17", 10, 19, 8, 10))
        candles.append(_candle("2025-01-18", 10, 20, 8, 10))  # bearish fractal
        candles.append(_candle("2025-01-19", 10, 19, 8, 10))
        candles.append(_candle("2025-01-20", 10, 18, 8, 10))
        # Trailing candles (indices 20-28)
        for i in range(9):
            candles.append(_candle(f"2025-01-{21+i:02d}", 10, 12, 8, 10))
        # Final candle with target close
        candles.append(_candle("2025-01-30", close_price, close_price + 1,
                               close_price - 1, close_price))
        return candles

    def test_long_breakout(self):
        """Close above bearish fractal -> LONG signal."""
        candles = self._make_candles_with_fractals(close_price=21)
        rules = {"rr_ratio": 2.0}
        sig = fractal_signal(candles, rules)
        self.assertIsNotNone(sig)
        self.assertEqual(sig["direction"], "LONG")
        self.assertIn("fractal breakout above", sig["reason"])

    def test_short_breakdown(self):
        """Close below bullish fractal -> SHORT signal."""
        candles = self._make_candles_with_fractals(close_price=4)
        rules = {"rr_ratio": 2.0}
        sig = fractal_signal(candles, rules)
        self.assertIsNotNone(sig)
        self.assertEqual(sig["direction"], "SHORT")
        self.assertIn("fractal breakdown below", sig["reason"])

    def test_no_breakout(self):
        """Price between fractals -> no signal."""
        candles = self._make_candles_with_fractals(close_price=10)
        rules = {"rr_ratio": 2.0}
        sig = fractal_signal(candles, rules)
        self.assertIsNone(sig)

    def test_sl_at_opposing_fractal(self):
        """LONG stop loss is at bullish fractal level."""
        candles = self._make_candles_with_fractals(close_price=21)
        rules = {"rr_ratio": 2.0}
        sig = fractal_signal(candles, rules)
        self.assertIsNotNone(sig)
        self.assertEqual(sig["stop_loss"], 5)  # bullish fractal low

    def test_rr_ratio(self):
        """Take profit = entry + stop_distance * rr_ratio."""
        candles = self._make_candles_with_fractals(close_price=21)
        rules = {"rr_ratio": 2.0}
        sig = fractal_signal(candles, rules)
        stop_dist = sig["entry"] - sig["stop_loss"]
        expected_tp = sig["entry"] + stop_dist * 2.0
        self.assertAlmostEqual(sig["take_profit"], expected_tp, places=5)

    def test_atr_stop_override(self):
        """ATR-based stop overrides fractal stop when enabled and tighter."""
        candles = self._make_candles_with_fractals(close_price=21)
        rules = {
            "rr_ratio": 2.0,
            "atr_stops": {"enabled": True, "multiplier": 0.5},
        }
        sig = fractal_signal(candles, rules)
        self.assertIsNotNone(sig)
        # ATR stop should be tighter than fractal stop at 5
        self.assertGreater(sig["stop_loss"], 5)

    def test_insufficient_candles(self):
        """Too few candles returns None."""
        candles = [_candle(f"2025-01-{i:02d}", 10, 12, 8, 10) for i in range(1, 6)]
        rules = {"rr_ratio": 2.0}
        sig = fractal_signal(candles, rules)
        self.assertIsNone(sig)


class TestClassifyFractalSignal(unittest.TestCase):

    def test_fractal_breakout(self):
        self.assertEqual(classify_signal("fractal breakout above 1.23"), "fractal")

    def test_fractal_breakdown(self):
        self.assertEqual(classify_signal("fractal breakdown below 50.00"), "fractal")

    def test_existing_trend_unaffected(self):
        self.assertEqual(classify_signal("uptrend (HH:4/9)"), "trend")

    def test_existing_sma_unaffected(self):
        self.assertEqual(classify_signal("SMA5>SMA20 (bullish)"), "sma")


if __name__ == "__main__":
    unittest.main()
