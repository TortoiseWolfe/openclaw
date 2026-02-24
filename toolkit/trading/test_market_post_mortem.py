#!/usr/bin/env python3
"""Tests for market_post_mortem.py — signal classification, confidence, and aggregates."""

import unittest

from market_post_mortem import (
    classify_signal,
    compute_confidence_multiplier,
    build_symbol_stats,
    compute_stop_analysis,
    analyze_trade,
)


class TestClassifySignal(unittest.TestCase):
    def test_uptrend(self):
        self.assertEqual(
            classify_signal("uptrend (HH:4/9), range: 1.17640"),
            "trend",
        )

    def test_downtrend(self):
        self.assertEqual(
            classify_signal("downtrend (LL:5/9), S/R: 155.30000"),
            "trend",
        )

    def test_sma_bullish(self):
        self.assertEqual(
            classify_signal("SMA5>SMA20 (bullish), range: 1.17640"),
            "sma",
        )

    def test_sma_bearish(self):
        self.assertEqual(
            classify_signal("SMA5<SMA20 (bearish), S/R: 692.00000"),
            "sma",
        )

    def test_pattern_bullish(self):
        self.assertEqual(
            classify_signal("ranging + bullish pin bar, range: 1.17640"),
            "pattern",
        )

    def test_pattern_bearish(self):
        self.assertEqual(
            classify_signal("ranging + bearish engulfing, S/R: 155.30000"),
            "pattern",
        )

    def test_range_near_support(self):
        self.assertEqual(
            classify_signal("ranging, near support (28%), range: 1.17640"),
            "range_position",
        )

    def test_range_near_resistance(self):
        self.assertEqual(
            classify_signal("ranging, near resistance (72%), S/R: 692.00"),
            "range_position",
        )

    def test_yolo_bullish(self):
        self.assertEqual(
            classify_signal("ranging, last candle bullish (YOLO), range: 1.17640"),
            "yolo",
        )

    def test_yolo_bearish(self):
        self.assertEqual(
            classify_signal("ranging, last candle bearish (YOLO), range: 1.17640"),
            "yolo",
        )

    def test_unknown(self):
        self.assertEqual(classify_signal("something unexpected"), "unknown")

    def test_empty_string(self):
        self.assertEqual(classify_signal(""), "unknown")


class TestComputeConfidenceMultiplier(unittest.TestCase):
    def test_below_min_sample(self):
        self.assertEqual(compute_confidence_multiplier(0, 0.5), 1.0)
        self.assertEqual(compute_confidence_multiplier(1, 0.8), 1.0)
        self.assertEqual(compute_confidence_multiplier(2, 0.0), 1.0)

    def test_at_breakeven_returns_one(self):
        # Breakeven for 1.5 RR is 0.4
        result = compute_confidence_multiplier(5, 0.4)
        self.assertEqual(result, 1.0)

    def test_high_win_rate_3_trades(self):
        # 100% WR with 3 trades — clamped to 1.25
        result = compute_confidence_multiplier(3, 1.0)
        self.assertEqual(result, 1.25)

    def test_zero_win_rate_3_trades(self):
        # 0% WR with 3 trades — clamped to 0.75
        result = compute_confidence_multiplier(3, 0.0)
        self.assertEqual(result, 0.75)

    def test_high_win_rate_10_trades(self):
        # 100% WR with 10+ trades — full range
        result = compute_confidence_multiplier(10, 1.0)
        self.assertEqual(result, 1.5)

    def test_zero_win_rate_10_trades(self):
        # 0% WR with 10+ trades — deviation from 0.4 breakeven = -0.4
        # raw = 1.0 + (-0.4/0.5)*0.5 = 0.6, clamped to [0.25, 1.5]
        result = compute_confidence_multiplier(10, 0.0)
        self.assertEqual(result, 0.6)

    def test_moderate_win_rate(self):
        # 60% WR with 5 trades — should be > 1.0
        result = compute_confidence_multiplier(5, 0.6)
        self.assertGreater(result, 1.0)
        self.assertLessEqual(result, 1.25)

    def test_low_win_rate(self):
        # 20% WR with 5 trades — should be < 1.0
        result = compute_confidence_multiplier(5, 0.2)
        self.assertLess(result, 1.0)
        self.assertGreaterEqual(result, 0.75)


class TestBuildSymbolStats(unittest.TestCase):
    def _make_detail(self, symbol, pnl, close_date="2026-02-13"):
        return {
            "id": f"T{id(symbol)}",
            "signal_type": "trend",
            "asset_class": "forex",
            "symbol": symbol,
            "direction": "LONG",
            "pnl_dollars": pnl,
            "close_reason": "stop loss" if pnl < 0 else "take profit",
            "entry_date": "2026-02-10",
            "close_date": close_date,
            "time_in_trade_days": 3,
            "max_adverse_excursion_pct": 0.01,
            "max_favorable_excursion_pct": 0.005,
            "trend_continued": None,
            "stop_distance_pct": 0.01,
            "rr_achieved": 1.5 if pnl > 0 else -1.0,
            "stopped_on_noise": False,
        }

    def test_no_skip_when_few_trades(self):
        details = [self._make_detail("EURUSD", -10) for _ in range(3)]
        result = build_symbol_stats(details)
        self.assertFalse(result["EURUSD"]["skip"])

    def test_skip_when_persistent_loser(self):
        details = [self._make_detail("USDJPY", -10) for _ in range(5)]
        result = build_symbol_stats(details)
        self.assertTrue(result["USDJPY"]["skip"])

    def test_no_skip_when_win_rate_ok(self):
        details = ([self._make_detail("SPY", 20) for _ in range(3)] +
                   [self._make_detail("SPY", -10) for _ in range(2)])
        result = build_symbol_stats(details)
        self.assertFalse(result["SPY"]["skip"])

    def test_no_skip_when_avg_pnl_positive(self):
        # Even with low win rate, if avg P&L is positive (big wins), don't skip
        details = ([self._make_detail("NVDA", 100)] +
                   [self._make_detail("NVDA", -5) for _ in range(4)])
        result = build_symbol_stats(details)
        self.assertFalse(result["NVDA"]["skip"])

    def test_streak_tracks_consecutive(self):
        details = [
            self._make_detail("EURUSD", 10, "2026-02-10"),
            self._make_detail("EURUSD", -5, "2026-02-11"),
            self._make_detail("EURUSD", -5, "2026-02-12"),
            self._make_detail("EURUSD", -5, "2026-02-13"),
        ]
        result = build_symbol_stats(details)
        self.assertEqual(result["EURUSD"]["streak"], -3)


class TestComputeStopAnalysis(unittest.TestCase):
    def _make_detail(self, close_reason, stopped_on_noise=False, stop_dist=0.01):
        return {
            "close_reason": close_reason,
            "stopped_on_noise": stopped_on_noise,
            "stop_distance_pct": stop_dist,
        }

    def test_no_stop_loss_trades(self):
        details = [self._make_detail("take profit"),
                   self._make_detail("weekend close")]
        result = compute_stop_analysis(details)
        self.assertEqual(result["optimal_stop_multiplier"], 1.0)

    def test_low_noise_no_adjustment(self):
        details = [self._make_detail("stop loss", False) for _ in range(5)]
        result = compute_stop_analysis(details)
        self.assertEqual(result["optimal_stop_multiplier"], 1.0)

    def test_high_noise_widens_stops(self):
        # 3 out of 5 stop-loss trades were noise (60%)
        details = ([self._make_detail("stop loss", True) for _ in range(3)] +
                   [self._make_detail("stop loss", False) for _ in range(2)])
        result = compute_stop_analysis(details)
        self.assertGreater(result["optimal_stop_multiplier"], 1.0)
        self.assertLessEqual(result["optimal_stop_multiplier"], 1.5)

    def test_noise_below_min_sample_no_adjustment(self):
        # Only 2 stop-loss trades (below MIN_SAMPLE_SIZE of 3)
        details = [self._make_detail("stop loss", True) for _ in range(2)]
        result = compute_stop_analysis(details)
        self.assertEqual(result["optimal_stop_multiplier"], 1.0)


class TestAnalyzeTrade(unittest.TestCase):
    def test_long_trade_with_candles(self):
        trade = {
            "id": "T001",
            "asset_class": "forex",
            "symbol": "EURUSD",
            "direction": "LONG",
            "entry": 1.1000,
            "exit": 1.0950,
            "stop_loss": 1.0900,
            "take_profit": 1.1150,
            "size": 10000,
            "pnl_dollars": -50.0,
            "close_reason": "stop loss",
            "date_opened": "2026-02-10",
            "date_closed": "2026-02-12",
            "reason": "uptrend (HH:4/9), range: 1.09000",
        }
        candles = [
            {"date": "2026-02-10", "o": 1.1000, "h": 1.1020, "l": 1.0960, "c": 1.0980},
            {"date": "2026-02-11", "o": 1.0980, "h": 1.1010, "l": 1.0940, "c": 1.0960},
            {"date": "2026-02-12", "o": 1.0960, "h": 1.0970, "l": 1.0920, "c": 1.0950},
            # Post-close candles for trend continuation
            {"date": "2026-02-13", "o": 1.0950, "h": 1.1000, "l": 1.0940, "c": 1.0990},
            {"date": "2026-02-14", "o": 1.0990, "h": 1.1050, "l": 1.0980, "c": 1.1040},
            {"date": "2026-02-17", "o": 1.1040, "h": 1.1060, "l": 1.1020, "c": 1.1050},
        ]

        result = analyze_trade(trade, candles)

        self.assertEqual(result["signal_type"], "trend")
        self.assertEqual(result["time_in_trade_days"], 2)
        self.assertIsNotNone(result["max_adverse_excursion_pct"])
        self.assertIsNotNone(result["max_favorable_excursion_pct"])
        # Price recovered after stop loss → trend continued
        self.assertTrue(result["trend_continued"])
        # Stopped out but trend continued → noise stop
        self.assertTrue(result["stopped_on_noise"])

    def test_short_trade(self):
        trade = {
            "id": "T002",
            "asset_class": "stocks",
            "symbol": "SPY",
            "direction": "SHORT",
            "entry": 700.0,
            "exit": 710.0,
            "stop_loss": 715.0,
            "take_profit": 677.5,
            "size": 10,
            "pnl_dollars": -100.0,
            "close_reason": "stop loss",
            "date_opened": "2026-02-10",
            "date_closed": "2026-02-11",
            "reason": "downtrend (LL:5/9), range: 690.00000",
        }
        candles = [
            {"date": "2026-02-10", "o": 700.0, "h": 705.0, "l": 695.0, "c": 702.0},
            {"date": "2026-02-11", "o": 702.0, "h": 712.0, "l": 700.0, "c": 710.0},
        ]

        result = analyze_trade(trade, candles)

        self.assertEqual(result["signal_type"], "trend")
        self.assertEqual(result["direction"], "SHORT")
        # MAE for SHORT: max (high - entry) / entry
        self.assertGreater(result["max_adverse_excursion_pct"], 0)

    def test_no_candles_returns_none_excursions(self):
        trade = {
            "id": "T003",
            "asset_class": "forex",
            "symbol": "GBPUSD",
            "direction": "LONG",
            "entry": 1.3600,
            "exit": 1.3600,
            "stop_loss": 1.3500,
            "take_profit": 1.3750,
            "size": 5000,
            "pnl_dollars": 0.0,
            "close_reason": "weekend close",
            "date_opened": "2026-02-13",
            "date_closed": "2026-02-13",
            "reason": "uptrend (HH:4/9), range: 1.35000",
        }

        result = analyze_trade(trade, [])

        self.assertIsNone(result["max_adverse_excursion_pct"])
        self.assertIsNone(result["max_favorable_excursion_pct"])
        self.assertIsNone(result["trend_continued"])
        self.assertFalse(result["stopped_on_noise"])


if __name__ == "__main__":
    unittest.main()
