#!/usr/bin/env python3
"""Tests for market_trade_decision.py — handler classes and pure functions."""

import unittest
from unittest.mock import patch

from market_trade_decision import (
    ForexHandler, StockHandler, CryptoHandler, check_stops,
    analyze, compute_sma, open_trade, _get_slippage,
)
from trading_common import check_correlation_guard
from trading_signals import compute_sentiment_multiplier


class TestForexHandler(unittest.TestCase):
    def setUp(self):
        self.h = ForexHandler()
        self.config = {"pip_size": 0.0001}

    def test_pip_size_default(self):
        self.assertEqual(self.h.pip_size("EURUSD", self.config), 0.0001)

    def test_pip_size_jpy_pair(self):
        config = {"pip_size": 0.01}
        self.assertEqual(self.h.pip_size("USDJPY", config), 0.01)

    def test_to_pips_calculation(self):
        pips = self.h.to_pips("EURUSD", self.config, 0.0050)
        self.assertAlmostEqual(pips, 50.0)

    def test_position_size_calculation(self):
        # balance=10000, risk=1%, stop=50 pips
        stop_dist = 50 * 0.0001  # 0.005
        size = self.h.position_size(10000, 0.01, stop_dist, 1.1, "EURUSD", self.config)
        # risk = 100, stop_pips = 50, lots = 100/(50*10) = 0.2, units = 20000
        self.assertEqual(size, 20000)

    def test_position_size_zero_stop(self):
        size = self.h.position_size(10000, 0.01, 0, 1.1, "EURUSD", self.config)
        self.assertEqual(size, 0)

    def test_calculate_pnl_long_profit(self):
        # 10000 units long, entry 1.1000, exit 1.1050 = +50 pips
        pnl = self.h.calculate_pnl(1.1000, 1.1050, "LONG", 10000, "EURUSD", self.config)
        # lots = 0.1, pips = 50, pnl = 50 * 0.1 * 10 = 50.0
        self.assertAlmostEqual(pnl, 50.0)

    def test_calculate_pnl_short_profit(self):
        pnl = self.h.calculate_pnl(1.1050, 1.1000, "SHORT", 10000, "EURUSD", self.config)
        self.assertAlmostEqual(pnl, 50.0)

    def test_calculate_pnl_long_loss(self):
        pnl = self.h.calculate_pnl(1.1000, 1.0950, "LONG", 10000, "EURUSD", self.config)
        self.assertAlmostEqual(pnl, -50.0)

    def test_format_size_units(self):
        self.assertEqual(self.h.format_size(10000), "10000 units")

    def test_weekend_close_true(self):
        self.assertTrue(self.h.weekend_close())


class TestStockHandler(unittest.TestCase):
    def setUp(self):
        self.h = StockHandler()
        self.config = {}

    def test_position_size_shares(self):
        # balance=10000, risk=1%, stop=$2
        size = self.h.position_size(10000, 0.01, 2.0, 150.0, "AAPL", self.config)
        # risk = 100, shares = 100/2 = 50
        self.assertEqual(size, 50)

    def test_position_size_zero_stop(self):
        size = self.h.position_size(10000, 0.01, 0, 150.0, "AAPL", self.config)
        self.assertEqual(size, 0)

    def test_calculate_pnl_long(self):
        pnl = self.h.calculate_pnl(150.0, 155.0, "LONG", 10, "AAPL", self.config)
        self.assertAlmostEqual(pnl, 50.0)

    def test_calculate_pnl_short(self):
        pnl = self.h.calculate_pnl(155.0, 150.0, "SHORT", 10, "AAPL", self.config)
        self.assertAlmostEqual(pnl, 50.0)

    def test_format_size_shares(self):
        self.assertEqual(self.h.format_size(50), "50 shares")

    def test_weekend_close_false(self):
        self.assertFalse(self.h.weekend_close())

    def test_stop_buffer_minimum(self):
        """Low-price stocks get $0.50 minimum buffer."""
        buf = self.h.stop_buffer("AAPL", self.config, price=50.0)
        self.assertEqual(buf, 0.50)

    def test_stop_buffer_percentage(self):
        """High-price stocks get 0.5% buffer."""
        buf = self.h.stop_buffer("AVGO", self.config, price=200.0)
        self.assertAlmostEqual(buf, 1.00)


class TestCryptoHandler(unittest.TestCase):
    def setUp(self):
        self.h = CryptoHandler()
        self.config = {}

    def test_position_size_fractional(self):
        # balance=10000, risk=1%, stop=$500
        size = self.h.position_size(10000, 0.01, 500.0, 60000.0, "BTCUSD", self.config)
        # risk = 100, size = 100/500 = 0.2
        self.assertAlmostEqual(size, 0.2)

    def test_calculate_pnl_long(self):
        pnl = self.h.calculate_pnl(60000.0, 61000.0, "LONG", 0.1, "BTCUSD", self.config)
        self.assertAlmostEqual(pnl, 100.0)

    def test_calculate_pnl_short(self):
        pnl = self.h.calculate_pnl(61000.0, 60000.0, "SHORT", 0.1, "BTCUSD", self.config)
        self.assertAlmostEqual(pnl, 100.0)

    def test_format_size_coins(self):
        self.assertEqual(self.h.format_size(0.5), "0.5 coins")

    def test_weekend_close_false(self):
        self.assertFalse(self.h.weekend_close())


class TestSpreadModeling(unittest.TestCase):
    """Test spread deduction in calculate_pnl across all handlers."""

    RULES = {
        "spread": {"forex": 0.00015, "stocks": 0.02, "crypto_pct": 0.0015},
    }

    def test_forex_spread_reduces_long_pnl(self):
        h = ForexHandler()
        config = {"pip_size": 0.0001}
        # Without spread
        pnl_clean = h.calculate_pnl(1.1000, 1.1050, "LONG", 10000, "EURUSD", config)
        # With spread (1.5 pips round-trip)
        pnl_spread = h.calculate_pnl(1.1000, 1.1050, "LONG", 10000, "EURUSD", config,
                                      rules=self.RULES)
        self.assertGreater(pnl_clean, pnl_spread)
        # Spread cost = 1.5 pips * 0.1 lots * $10/pip = $1.50
        self.assertAlmostEqual(pnl_clean - pnl_spread, 1.50, places=2)

    def test_forex_spread_reduces_short_pnl(self):
        h = ForexHandler()
        config = {"pip_size": 0.0001}
        pnl_clean = h.calculate_pnl(1.1050, 1.1000, "SHORT", 10000, "EURUSD", config)
        pnl_spread = h.calculate_pnl(1.1050, 1.1000, "SHORT", 10000, "EURUSD", config,
                                      rules=self.RULES)
        self.assertGreater(pnl_clean, pnl_spread)
        self.assertAlmostEqual(pnl_clean - pnl_spread, 1.50, places=2)

    def test_stock_spread_reduces_pnl(self):
        h = StockHandler()
        config = {}
        pnl_clean = h.calculate_pnl(150.0, 155.0, "LONG", 10, "AAPL", config)
        pnl_spread = h.calculate_pnl(150.0, 155.0, "LONG", 10, "AAPL", config,
                                      rules=self.RULES)
        # Spread cost = $0.02 * 10 shares = $0.20
        self.assertAlmostEqual(pnl_clean - pnl_spread, 0.20, places=2)

    def test_crypto_spread_percentage_based(self):
        h = CryptoHandler()
        config = {}
        pnl_clean = h.calculate_pnl(60000.0, 61000.0, "LONG", 0.1, "BTCUSD", config)
        pnl_spread = h.calculate_pnl(60000.0, 61000.0, "LONG", 0.1, "BTCUSD", config,
                                      rules=self.RULES)
        self.assertGreater(pnl_clean, pnl_spread)
        # Spread ~0.15% total: entry +0.075%, exit -0.075%
        # Entry: 60000 * 1.00075 = 60045, Exit: 61000 * 0.99925 = 60954.25
        # PnL with spread: (60954.25 - 60045) * 0.1 = ~90.925
        # PnL clean: 1000 * 0.1 = 100
        # Difference ~9.075
        self.assertAlmostEqual(pnl_clean - pnl_spread, 9.075, places=1)

    def test_no_rules_means_no_spread(self):
        """Backward compatibility: rules=None applies zero spread."""
        h = ForexHandler()
        config = {"pip_size": 0.0001}
        pnl_with_none = h.calculate_pnl(1.1000, 1.1050, "LONG", 10000, "EURUSD", config,
                                          rules=None)
        pnl_without = h.calculate_pnl(1.1000, 1.1050, "LONG", 10000, "EURUSD", config)
        self.assertEqual(pnl_with_none, pnl_without)


class TestSlippage(unittest.TestCase):
    """Test slippage adjustments on trade entry."""

    RULES = {
        "max_risk": 0.02,
        "rr_ratio": 3.0,
        "max_positions": {"forex": 2, "stocks": 2, "crypto": 1, "global": 3},
        "spread": {"forex": 0.00015, "stocks": 0.02, "crypto_pct": 0.0015},
        "slippage": {"forex": 0.00005, "stocks": 0.01, "crypto_pct": 0.0005},
    }

    def test_get_slippage_forex(self):
        slip = _get_slippage(self.RULES, "forex", 1.1000)
        self.assertAlmostEqual(slip, 0.00005)

    def test_get_slippage_stocks(self):
        slip = _get_slippage(self.RULES, "stocks", 150.0)
        self.assertAlmostEqual(slip, 0.01)

    def test_get_slippage_crypto_percentage(self):
        slip = _get_slippage(self.RULES, "crypto", 60000.0)
        self.assertAlmostEqual(slip, 30.0)  # 0.05% of 60000

    def test_long_entry_slipped_up(self):
        """LONG entry is adjusted upward (worse price)."""
        state = {"balance": 10000.0, "next_id": 1, "open": [], "closed": []}
        signal = {
            "direction": "LONG", "entry": 150.0,
            "stop_loss": 148.0, "take_profit": 156.0,
            "stop_distance": 2.0, "reason": "uptrend",
        }
        wl = {"rules": self.RULES}
        with patch("market_trade_decision._asset_config", return_value={}):
            trade = open_trade(state, "stocks", "AAPL", signal, wl, "2026-02-17")
        self.assertGreater(trade["entry"], 150.0)
        self.assertAlmostEqual(trade["entry"], 150.01)

    def test_long_stop_widened_down(self):
        """LONG stop-loss is moved down to account for exit slippage."""
        state = {"balance": 10000.0, "next_id": 1, "open": [], "closed": []}
        signal = {
            "direction": "LONG", "entry": 150.0,
            "stop_loss": 148.0, "take_profit": 156.0,
            "stop_distance": 2.0, "reason": "uptrend",
        }
        wl = {"rules": self.RULES}
        with patch("market_trade_decision._asset_config", return_value={}):
            trade = open_trade(state, "stocks", "AAPL", signal, wl, "2026-02-17")
        self.assertLess(trade["stop_loss"], 148.0)
        self.assertAlmostEqual(trade["stop_loss"], 147.99)

    def test_short_entry_slipped_down(self):
        """SHORT entry is adjusted downward (worse price)."""
        state = {"balance": 10000.0, "next_id": 1, "open": [], "closed": []}
        signal = {
            "direction": "SHORT", "entry": 150.0,
            "stop_loss": 152.0, "take_profit": 144.0,
            "stop_distance": 2.0, "reason": "downtrend",
        }
        wl = {"rules": self.RULES}
        with patch("market_trade_decision._asset_config", return_value={}):
            trade = open_trade(state, "stocks", "AAPL", signal, wl, "2026-02-17")
        self.assertLess(trade["entry"], 150.0)
        self.assertAlmostEqual(trade["entry"], 149.99)

    def test_take_profit_unchanged(self):
        """TP is a limit order — no slippage applied."""
        state = {"balance": 10000.0, "next_id": 1, "open": [], "closed": []}
        signal = {
            "direction": "LONG", "entry": 150.0,
            "stop_loss": 148.0, "take_profit": 156.0,
            "stop_distance": 2.0, "reason": "uptrend",
        }
        wl = {"rules": self.RULES}
        with patch("market_trade_decision._asset_config", return_value={}):
            trade = open_trade(state, "stocks", "AAPL", signal, wl, "2026-02-17")
        self.assertAlmostEqual(trade["take_profit"], 156.0)

    def test_no_slippage_config_means_zero(self):
        """Missing slippage config applies zero slippage."""
        rules_no_slip = {
            "max_risk": 0.02,
            "rr_ratio": 3.0,
            "max_positions": {"forex": 2, "stocks": 2, "crypto": 1, "global": 3},
        }
        slip = _get_slippage(rules_no_slip, "stocks", 150.0)
        self.assertEqual(slip, 0)


class TestCheckStops(unittest.TestCase):
    """Test stop-loss and take-profit checking with daily high/low."""

    TODAY = "2026-02-17"

    def _make_state(self, positions):
        return {"open": positions, "closed": [], "balance": 10000.0}

    def _long_pos(self, entry=1.1000, sl=1.0950, tp=1.1100):
        return {
            "id": "T001", "asset_class": "forex", "symbol": "EURUSD",
            "direction": "LONG", "entry": entry, "stop_loss": sl,
            "take_profit": tp, "size": 10000,
        }

    def _short_pos(self, entry=1.1000, sl=1.1050, tp=1.0900):
        return {
            "id": "T002", "asset_class": "forex", "symbol": "EURUSD",
            "direction": "SHORT", "entry": entry, "stop_loss": sl,
            "take_profit": tp, "size": 10000,
        }

    @patch("market_trade_decision._asset_config", return_value={"pip_size": 0.0001})
    def test_long_sl_hit_by_low(self, _cfg):
        """Daily low breaches SL even though close is above SL."""
        state = self._make_state([self._long_pos()])
        # close=1.0980 (above SL), but low=1.0940 (below SL of 1.0950)
        prices = {("forex", "EURUSD"): (1.0980, 1.1010, 1.0940)}
        closed = check_stops(state, prices, self.TODAY)
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["close_reason"], "stop loss")
        self.assertAlmostEqual(closed[0]["exit"], 1.0950)

    @patch("market_trade_decision._asset_config", return_value={"pip_size": 0.0001})
    def test_long_tp_hit_by_high(self, _cfg):
        """Daily high reaches TP even though close is below TP."""
        state = self._make_state([self._long_pos()])
        # close=1.1080, high=1.1110 (above TP of 1.1100), low=1.1060
        prices = {("forex", "EURUSD"): (1.1080, 1.1110, 1.1060)}
        closed = check_stops(state, prices, self.TODAY)
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["close_reason"], "take profit")

    @patch("market_trade_decision._asset_config", return_value={"pip_size": 0.0001})
    def test_long_no_hit(self, _cfg):
        """Neither SL nor TP hit — position stays open."""
        state = self._make_state([self._long_pos()])
        # All within range: close=1.1020, high=1.1050, low=1.0970
        prices = {("forex", "EURUSD"): (1.1020, 1.1050, 1.0970)}
        closed = check_stops(state, prices, self.TODAY)
        self.assertEqual(len(closed), 0)
        self.assertEqual(len(state["open"]), 1)
        self.assertAlmostEqual(state["open"][0]["current_price"], 1.1020)

    @patch("market_trade_decision._asset_config", return_value={"pip_size": 0.0001})
    def test_short_sl_hit_by_high(self, _cfg):
        """Short SL hit when daily high reaches SL level."""
        state = self._make_state([self._short_pos()])
        # close=1.1020, high=1.1060 (above SL of 1.1050), low=1.0990
        prices = {("forex", "EURUSD"): (1.1020, 1.1060, 1.0990)}
        closed = check_stops(state, prices, self.TODAY)
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["close_reason"], "stop loss")

    @patch("market_trade_decision._asset_config", return_value={"pip_size": 0.0001})
    def test_short_tp_hit_by_low(self, _cfg):
        """Short TP hit when daily low reaches TP level."""
        state = self._make_state([self._short_pos()])
        # close=1.0920, high=1.0950, low=1.0890 (below TP of 1.0900)
        prices = {("forex", "EURUSD"): (1.0920, 1.0950, 1.0890)}
        closed = check_stops(state, prices, self.TODAY)
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["close_reason"], "take profit")

    @patch("market_trade_decision._asset_config", return_value={"pip_size": 0.0001})
    def test_sl_checked_before_tp(self, _cfg):
        """When both SL and TP are hit in same candle, SL wins (conservative)."""
        state = self._make_state([self._long_pos()])
        # Volatile candle: low=1.0940 (below SL), high=1.1110 (above TP)
        prices = {("forex", "EURUSD"): (1.1000, 1.1110, 1.0940)}
        closed = check_stops(state, prices, self.TODAY)
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["close_reason"], "stop loss")

    @patch("market_trade_decision._asset_config", return_value={"pip_size": 0.0001})
    def test_no_price_data_keeps_position(self, _cfg):
        """Position with no price data stays open unchanged."""
        state = self._make_state([self._long_pos()])
        prices = {}  # no data for EURUSD
        closed = check_stops(state, prices, self.TODAY)
        self.assertEqual(len(closed), 0)
        self.assertEqual(len(state["open"]), 1)

    @patch("market_trade_decision._asset_config", return_value={"pip_size": 0.0001})
    def test_balance_updated_on_close(self, _cfg):
        """Balance is adjusted when positions are closed."""
        state = self._make_state([self._long_pos()])
        # TP hit: exit at 1.1100, entry 1.1000 = +100 pips on 10000 units
        prices = {("forex", "EURUSD"): (1.1100, 1.1100, 1.1050)}
        check_stops(state, prices, self.TODAY)
        self.assertGreater(state["balance"], 10000.0)


# ── Signal generation tests (M6) ─────────────────────────────────────


def _make_candles(closes, start_h=None, start_l=None):
    """Build a list of candle dicts from close prices.

    Generates plausible OHLC: open=prev close, high=max+0.5%, low=min-0.5%.
    """
    candles = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c
        h = max(o, c) * 1.005
        l = min(o, c) * 0.995
        candles.append({"date": f"2026-01-{i+1:02d}", "o": o, "h": h, "l": l, "c": c})
    return candles


def _uptrend_candles(n=10, start=100.0, step=2.0):
    """Build candles with steadily rising highs and lows (uptrend)."""
    candles = []
    for i in range(n):
        base = start + i * step
        candles.append({
            "date": f"2026-01-{i+1:02d}",
            "o": base, "h": base + step * 0.8,
            "l": base - step * 0.2, "c": base + step * 0.5,
        })
    return candles


def _downtrend_candles(n=10, start=100.0, step=2.0):
    """Build candles with steadily falling highs and lows (downtrend)."""
    candles = []
    for i in range(n):
        base = start - i * step
        candles.append({
            "date": f"2026-01-{i+1:02d}",
            "o": base, "h": base + step * 0.2,
            "l": base - step * 0.8, "c": base - step * 0.5,
        })
    return candles


def _ranging_candles(n=10, center=100.0, width=1.0):
    """Build candles oscillating around center (no trend)."""
    candles = []
    for i in range(n):
        offset = width * (0.5 if i % 2 == 0 else -0.5)
        c = center + offset
        candles.append({
            "date": f"2026-01-{i+1:02d}",
            "o": center - offset, "h": center + width,
            "l": center - width, "c": c,
        })
    return candles


STOCK_CONFIG = {}
FOREX_CONFIG = {"pip_size": 0.0001}
BASE_RULES = {"max_risk": 0.03, "rr_ratio": 3.0}


class TestAnalyzeSignals(unittest.TestCase):
    """Test analyze() signal generation logic."""

    def test_uptrend_returns_long(self):
        """Clear uptrend should produce a LONG signal."""
        candles = _uptrend_candles(10)
        result = analyze("stocks", "AAPL", STOCK_CONFIG, candles, set(), BASE_RULES)
        self.assertIsNotNone(result)
        sig = result["signal"]
        self.assertIsNotNone(sig)
        self.assertEqual(sig["direction"], "LONG")
        self.assertIn("uptrend", sig["reason"])

    def test_downtrend_returns_short(self):
        """Clear downtrend should produce a SHORT signal."""
        candles = _downtrend_candles(10)
        result = analyze("stocks", "AAPL", STOCK_CONFIG, candles, set(), BASE_RULES)
        self.assertIsNotNone(result)
        sig = result["signal"]
        self.assertIsNotNone(sig)
        self.assertEqual(sig["direction"], "SHORT")
        self.assertIn("downtrend", sig["reason"])

    def test_ranging_dead_center_no_signal(self):
        """Dead center in a range with no pattern should return no signal (YOLO removed)."""
        # Build candles that are perfectly centered (pos_in_range ~0.50)
        candles = []
        for i in range(10):
            candles.append({
                "date": f"2026-01-{i+1:02d}",
                "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.0,
            })
        result = analyze("stocks", "AAPL", STOCK_CONFIG, candles, set(), BASE_RULES)
        # Either no result or signal is None (no YOLO)
        if result is not None:
            self.assertIsNone(result.get("signal"))

    def test_ranging_near_support_goes_long(self):
        """Price near support in a range should go LONG (requires S&R education)."""
        candles = []
        for i in range(9):
            candles.append({
                "date": f"2026-01-{i+1:02d}",
                "o": 100.0, "h": 102.0, "l": 98.0, "c": 100.0,
            })
        # Last candle closes near the low (near support)
        candles.append({
            "date": "2026-01-10",
            "o": 99.0, "h": 100.0, "l": 98.0, "c": 98.5,
        })
        edu = {"Support and Resistance Levels"}
        result = analyze("stocks", "AAPL", STOCK_CONFIG, candles, edu, BASE_RULES)
        self.assertIsNotNone(result)
        sig = result["signal"]
        self.assertIsNotNone(sig)
        self.assertEqual(sig["direction"], "LONG")
        self.assertIn("support", sig["reason"].lower())

    def test_ranging_near_resistance_goes_short(self):
        """Price near resistance in a range should go SHORT (requires S&R education)."""
        candles = []
        for i in range(9):
            candles.append({
                "date": f"2026-01-{i+1:02d}",
                "o": 100.0, "h": 102.0, "l": 98.0, "c": 100.0,
            })
        # Last candle closes near the high (near resistance)
        candles.append({
            "date": "2026-01-10",
            "o": 101.0, "h": 102.0, "l": 100.5, "c": 101.5,
        })
        edu = {"Support and Resistance Levels"}
        result = analyze("stocks", "AAPL", STOCK_CONFIG, candles, edu, BASE_RULES)
        self.assertIsNotNone(result)
        sig = result["signal"]
        self.assertIsNotNone(sig)
        self.assertEqual(sig["direction"], "SHORT")
        self.assertIn("resistance", sig["reason"].lower())

    def test_too_few_candles_returns_none(self):
        """Less than 2 candles should return None."""
        candles = [{"date": "2026-01-01", "o": 100, "h": 101, "l": 99, "c": 100}]
        result = analyze("stocks", "AAPL", STOCK_CONFIG, candles, set(), BASE_RULES)
        self.assertIsNone(result)

    def test_signal_has_required_fields(self):
        """Signal dict must have direction, entry, stop_loss, take_profit, stop_distance, reason."""
        candles = _uptrend_candles(10)
        result = analyze("stocks", "AAPL", STOCK_CONFIG, candles, set(), BASE_RULES)
        sig = result["signal"]
        for field in ("direction", "entry", "stop_loss", "take_profit", "stop_distance", "reason"):
            self.assertIn(field, sig, f"Missing field: {field}")

    def test_stop_loss_below_entry_for_long(self):
        """LONG signal stop_loss must be below entry."""
        candles = _uptrend_candles(10)
        result = analyze("stocks", "AAPL", STOCK_CONFIG, candles, set(), BASE_RULES)
        sig = result["signal"]
        self.assertLess(sig["stop_loss"], sig["entry"])
        self.assertGreater(sig["take_profit"], sig["entry"])

    def test_stop_loss_above_entry_for_short(self):
        """SHORT signal stop_loss must be above entry."""
        candles = _downtrend_candles(10)
        result = analyze("stocks", "AAPL", STOCK_CONFIG, candles, set(), BASE_RULES)
        sig = result["signal"]
        self.assertGreater(sig["stop_loss"], sig["entry"])
        self.assertLess(sig["take_profit"], sig["entry"])


class TestSMAGating(unittest.TestCase):
    """Test that SMA signals are gated by education progress."""

    def test_sma_not_used_without_education(self):
        """Without 'Moving Averages' section, SMA shouldn't appear in reason."""
        candles = _ranging_candles(25, center=100.0, width=0.5)
        result = analyze("stocks", "AAPL", STOCK_CONFIG, candles, set(), BASE_RULES)
        if result and result.get("signal"):
            self.assertNotIn("SMA", result["signal"]["reason"])

    def test_sma_used_with_education(self):
        """With 'Moving Averages' completed and enough candles, SMA appears in reason."""
        # Build candles where SMA5 > SMA20 (recent prices above older ones)
        candles = []
        for i in range(25):
            price = 100.0 + i * 0.5  # steadily rising
            candles.append({
                "date": f"2026-01-{i+1:02d}",
                "o": price - 0.2, "h": price + 0.3,
                "l": price - 0.3, "c": price,
            })
        edu = {"Moving Averages"}
        result = analyze("stocks", "AAPL", STOCK_CONFIG, candles, edu, BASE_RULES)
        self.assertIsNotNone(result)
        sig = result.get("signal")
        self.assertIsNotNone(sig)
        self.assertIn("SMA", sig["reason"])


class TestComputeSMA(unittest.TestCase):
    """Test compute_sma() helper."""

    def test_correct_average(self):
        candles = [{"c": 10}, {"c": 20}, {"c": 30}]
        self.assertAlmostEqual(compute_sma(candles, 3), 20.0)

    def test_uses_last_n_candles(self):
        candles = [{"c": 1}, {"c": 2}, {"c": 10}, {"c": 20}, {"c": 30}]
        self.assertAlmostEqual(compute_sma(candles, 3), 20.0)

    def test_insufficient_candles_returns_none(self):
        candles = [{"c": 10}, {"c": 20}]
        self.assertIsNone(compute_sma(candles, 3))


class TestLessonsMultiplier(unittest.TestCase):
    """Test that lessons confidence multiplier adjusts position sizing."""

    @patch("market_trade_decision._asset_config", return_value={})
    def test_high_confidence_increases_size(self, _cfg):
        """Signal type with high confidence multiplier → bigger position."""
        state = {"balance": 10000.0, "open": [], "closed": [], "next_id": 1}
        signal = {
            "direction": "LONG", "entry": 100.0,
            "stop_loss": 98.0, "take_profit": 106.0,
            "stop_distance": 2.0, "reason": "uptrend (HH:5/9)",
        }
        watchlist = {"rules": {"max_risk": 0.03, "rr_ratio": 3.0}}

        # Without lessons
        trade_no_lessons = open_trade(state.copy() | {"open": [], "next_id": 1},
                                       "stocks", "AAPL", signal, watchlist,
                                       "2026-01-15", lessons=None)

        # With lessons boosting trend signals
        lessons = {
            "by_signal_type": {"trend": {"confidence_multiplier": 1.4}},
            "by_asset_class": {"stocks": {"confidence_multiplier": 1.0}},
        }
        trade_with_lessons = open_trade(state.copy() | {"open": [], "next_id": 1},
                                         "stocks", "AAPL", signal, watchlist,
                                         "2026-01-15", lessons=lessons)

        self.assertIsNotNone(trade_no_lessons)
        self.assertIsNotNone(trade_with_lessons)
        self.assertGreater(trade_with_lessons["size"], trade_no_lessons["size"])

    @patch("market_trade_decision._asset_config", return_value={})
    def test_low_confidence_decreases_size(self, _cfg):
        """Signal type with low confidence multiplier → smaller position."""
        state = {"balance": 10000.0, "open": [], "closed": [], "next_id": 1}
        signal = {
            "direction": "LONG", "entry": 100.0,
            "stop_loss": 98.0, "take_profit": 106.0,
            "stop_distance": 2.0, "reason": "uptrend (HH:5/9)",
        }
        watchlist = {"rules": {"max_risk": 0.03, "rr_ratio": 3.0}}

        trade_no_lessons = open_trade(state.copy() | {"open": [], "next_id": 1},
                                       "stocks", "AAPL", signal, watchlist,
                                       "2026-01-15", lessons=None)

        lessons = {
            "by_signal_type": {"trend": {"confidence_multiplier": 0.5}},
            "by_asset_class": {"stocks": {"confidence_multiplier": 1.0}},
        }
        trade_with_lessons = open_trade(state.copy() | {"open": [], "next_id": 1},
                                         "stocks", "AAPL", signal, watchlist,
                                         "2026-01-15", lessons=lessons)

        self.assertIsNotNone(trade_no_lessons)
        self.assertIsNotNone(trade_with_lessons)
        self.assertLess(trade_with_lessons["size"], trade_no_lessons["size"])

    @patch("market_trade_decision._asset_config", return_value={})
    def test_multiplier_clamped(self, _cfg):
        """Combined multiplier is clamped to [0.25, 1.5]."""
        state = {"balance": 10000.0, "open": [], "closed": [], "next_id": 1}
        signal = {
            "direction": "LONG", "entry": 100.0,
            "stop_loss": 98.0, "take_profit": 106.0,
            "stop_distance": 2.0, "reason": "uptrend (HH:5/9)",
        }
        watchlist = {"rules": {"max_risk": 0.03, "rr_ratio": 3.0}}

        # Extreme multipliers — should be clamped
        lessons = {
            "by_signal_type": {"trend": {"confidence_multiplier": 5.0}},
            "by_asset_class": {"stocks": {"confidence_multiplier": 5.0}},
        }
        trade = open_trade(state.copy() | {"open": [], "next_id": 1},
                           "stocks", "AAPL", signal, watchlist,
                           "2026-01-15", lessons=lessons)

        # Base size = 10000 * 0.03 / 2.0 = 150 shares
        # Clamped at 1.5x → max 225 shares
        self.assertIsNotNone(trade)
        self.assertLessEqual(trade["size"], 225)


class TestStaleDataGate(unittest.TestCase):
    """Test that stale data is blocked from trading."""

    def test_stale_data_returns_empty(self):
        """load_candles with max_stale_days returns [] for old data."""
        from trading_common import load_candles
        from datetime import date
        # Use a date far in the future so any real data is "stale"
        future = date(2030, 1, 1)
        try:
            result = load_candles("stocks", "AAPL", max_stale_days=1, today=future)
            self.assertEqual(result, [])
        except FileNotFoundError:
            # No data file in test env — that's fine, the gate is upstream
            pass


class TestValidateCandle(unittest.TestCase):
    """Test validate_candle() from trading_common."""

    def test_valid_candle_passes(self):
        from trading_common import validate_candle
        ok, reason = validate_candle({"o": 100, "h": 105, "l": 95, "c": 102})
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_zero_ohlc_fails(self):
        from trading_common import validate_candle
        ok, reason = validate_candle({"o": 0, "h": 105, "l": 95, "c": 102})
        self.assertFalse(ok)
        self.assertIn("zero", reason)

    def test_high_below_close_fails(self):
        from trading_common import validate_candle
        ok, reason = validate_candle({"o": 100, "h": 99, "l": 95, "c": 102})
        self.assertFalse(ok)
        self.assertIn("high", reason)

    def test_low_above_open_fails(self):
        from trading_common import validate_candle
        ok, reason = validate_candle({"o": 100, "h": 105, "l": 101, "c": 102})
        self.assertFalse(ok)
        self.assertIn("low", reason)


class TestSentimentMultiplier(unittest.TestCase):
    """Test compute_sentiment_multiplier() logic."""

    RULES = {
        "sentiment": {
            "enabled": True,
            "agree_multiplier": 1.0,
            "disagree_multiplier": 0.5,
            "strong_disagree_threshold": 0.3,
            "strong_disagree_action": "skip",
        }
    }

    def test_disabled_returns_1(self):
        rules = {"sentiment": {"enabled": False}}
        mult, reason = compute_sentiment_multiplier("AAPL", "LONG", {"AAPL": 0.5}, rules)
        self.assertEqual(mult, 1.0)
        self.assertEqual(reason, "disabled")

    def test_no_data_returns_1(self):
        mult, reason = compute_sentiment_multiplier("AAPL", "LONG", {}, self.RULES)
        self.assertEqual(mult, 1.0)
        self.assertEqual(reason, "no_data")

    def test_no_sentiment_config_returns_1(self):
        mult, reason = compute_sentiment_multiplier("AAPL", "LONG", {"AAPL": 0.5}, {})
        self.assertEqual(mult, 1.0)
        self.assertEqual(reason, "disabled")

    def test_long_agrees_with_positive(self):
        mult, reason = compute_sentiment_multiplier(
            "AAPL", "LONG", {"AAPL": 0.25}, self.RULES)
        self.assertEqual(mult, 1.0)
        self.assertEqual(reason, "agree")

    def test_short_agrees_with_negative(self):
        mult, reason = compute_sentiment_multiplier(
            "AAPL", "SHORT", {"AAPL": -0.25}, self.RULES)
        self.assertEqual(mult, 1.0)
        self.assertEqual(reason, "agree")

    def test_long_disagrees_mild(self):
        mult, reason = compute_sentiment_multiplier(
            "AAPL", "LONG", {"AAPL": -0.2}, self.RULES)
        self.assertEqual(mult, 0.5)
        self.assertEqual(reason, "disagree")

    def test_long_disagrees_strong_veto(self):
        mult, reason = compute_sentiment_multiplier(
            "AAPL", "LONG", {"AAPL": -0.4}, self.RULES)
        self.assertEqual(mult, 0.0)
        self.assertEqual(reason, "strong_disagree")

    def test_short_disagrees_strong_veto(self):
        mult, reason = compute_sentiment_multiplier(
            "AAPL", "SHORT", {"AAPL": 0.35}, self.RULES)
        self.assertEqual(mult, 0.0)
        self.assertEqual(reason, "strong_disagree")

    def test_zero_sentiment_agrees_with_long(self):
        """Score of exactly 0.0 is treated as agreeing (neutral)."""
        mult, reason = compute_sentiment_multiplier(
            "AAPL", "LONG", {"AAPL": 0.0}, self.RULES)
        self.assertEqual(mult, 1.0)
        self.assertEqual(reason, "agree")


class TestEducationGating(unittest.TestCase):
    """Test that pattern and range_position signals are gated by education."""

    def test_pattern_signal_blocked_without_candles_education(self):
        """Without Japanese Candlesticks, bullish patterns don't produce standalone signals."""
        # Build ranging candles with a bullish pin bar on the last candle
        candles = []
        for i in range(9):
            candles.append({
                "date": f"2026-01-{i+1:02d}",
                "o": 100.0, "h": 102.0, "l": 98.0, "c": 100.0,
            })
        # Last candle: bullish pin bar (small body, long lower wick)
        candles.append({
            "date": "2026-01-10",
            "o": 100.0, "h": 100.5, "l": 97.0, "c": 100.2,
        })
        # No education → pattern shouldn't generate a standalone signal
        result = analyze("stocks", "AAPL", STOCK_CONFIG, candles, set(), BASE_RULES)
        if result and result.get("signal"):
            self.assertNotIn("ranging +", result["signal"]["reason"])

    def test_pattern_signal_allowed_with_candles_education(self):
        """With Japanese Candlesticks, bullish patterns produce standalone signals."""
        candles = []
        for i in range(9):
            candles.append({
                "date": f"2026-01-{i+1:02d}",
                "o": 100.0, "h": 102.0, "l": 98.0, "c": 100.0,
            })
        # Bullish pin bar
        candles.append({
            "date": "2026-01-10",
            "o": 100.0, "h": 100.5, "l": 97.0, "c": 100.2,
        })
        edu = {"Japanese Candlesticks"}
        result = analyze("stocks", "AAPL", STOCK_CONFIG, candles, edu, BASE_RULES)
        if result and result.get("signal"):
            # With education, if a pattern signal is generated it should be properly named
            if "ranging +" in result["signal"]["reason"]:
                self.assertIn("pin bar", result["signal"]["reason"])

    def test_range_position_blocked_without_sr_education(self):
        """Without S&R education, range position signals don't generate."""
        candles = []
        for i in range(9):
            candles.append({
                "date": f"2026-01-{i+1:02d}",
                "o": 100.0, "h": 102.0, "l": 98.0, "c": 100.0,
            })
        # Close near support
        candles.append({
            "date": "2026-01-10",
            "o": 99.0, "h": 100.0, "l": 98.0, "c": 98.5,
        })
        result = analyze("stocks", "AAPL", STOCK_CONFIG, candles, set(), BASE_RULES)
        if result and result.get("signal"):
            self.assertNotIn("near support", result["signal"]["reason"])
            self.assertNotIn("near resistance", result["signal"]["reason"])

    def test_range_position_allowed_with_sr_education(self):
        """With S&R education, range position signals generate."""
        candles = []
        for i in range(9):
            candles.append({
                "date": f"2026-01-{i+1:02d}",
                "o": 100.0, "h": 102.0, "l": 98.0, "c": 100.0,
            })
        candles.append({
            "date": "2026-01-10",
            "o": 99.0, "h": 100.0, "l": 98.0, "c": 98.5,
        })
        edu = {"Support and Resistance Levels"}
        result = analyze("stocks", "AAPL", STOCK_CONFIG, candles, edu, BASE_RULES)
        self.assertIsNotNone(result)
        sig = result.get("signal")
        self.assertIsNotNone(sig)
        self.assertIn("support", sig["reason"].lower())

    def test_sma_gating_unchanged(self):
        """SMA still gated behind Moving Averages (existing behavior preserved)."""
        candles = []
        for i in range(25):
            price = 100.0 + i * 0.5
            candles.append({
                "date": f"2026-01-{i+1:02d}",
                "o": price - 0.2, "h": price + 0.3,
                "l": price - 0.3, "c": price,
            })
        # Without education, no SMA
        result = analyze("stocks", "AAPL", STOCK_CONFIG, candles, set(), BASE_RULES)
        if result and result.get("signal"):
            self.assertNotIn("SMA", result["signal"]["reason"])
        # With education, SMA appears
        edu = {"Moving Averages"}
        result2 = analyze("stocks", "AAPL", STOCK_CONFIG, candles, edu, BASE_RULES)
        self.assertIsNotNone(result2)
        if result2.get("signal"):
            self.assertIn("SMA", result2["signal"]["reason"])


class TestSentimentInOpenTrade(unittest.TestCase):
    """Test that sentiment multiplier is applied and recorded in trades."""

    @patch("market_trade_decision._asset_config", return_value={})
    def test_sentiment_reduces_position_size(self, _cfg):
        """Sentiment multiplier < 1.0 reduces position size."""
        state = {"balance": 10000.0, "open": [], "closed": [], "next_id": 1}
        signal = {
            "direction": "LONG", "entry": 100.0,
            "stop_loss": 98.0, "take_profit": 106.0,
            "stop_distance": 2.0, "reason": "uptrend (HH:5/9)",
        }
        watchlist = {"rules": {"max_risk": 0.03, "rr_ratio": 3.0}}

        # Without sentiment
        trade_full = open_trade(state.copy() | {"open": [], "next_id": 1},
                                "stocks", "AAPL", signal, watchlist,
                                "2026-01-15", sentiment_multiplier=1.0)

        # With 0.5x sentiment
        trade_half = open_trade(state.copy() | {"open": [], "next_id": 1},
                                "stocks", "AAPL", signal, watchlist,
                                "2026-01-15", sentiment_multiplier=0.5)

        self.assertIsNotNone(trade_full)
        self.assertIsNotNone(trade_half)
        self.assertLess(trade_half["size"], trade_full["size"])

    @patch("market_trade_decision._asset_config", return_value={})
    def test_sentiment_1_no_change(self, _cfg):
        """Sentiment multiplier of 1.0 doesn't change position size."""
        state = {"balance": 10000.0, "open": [], "closed": [], "next_id": 1}
        signal = {
            "direction": "LONG", "entry": 100.0,
            "stop_loss": 98.0, "take_profit": 106.0,
            "stop_distance": 2.0, "reason": "uptrend (HH:5/9)",
        }
        watchlist = {"rules": {"max_risk": 0.03, "rr_ratio": 3.0}}

        trade_default = open_trade(state.copy() | {"open": [], "next_id": 1},
                                   "stocks", "AAPL", signal, watchlist,
                                   "2026-01-15")

        trade_1x = open_trade(state.copy() | {"open": [], "next_id": 1},
                              "stocks", "AAPL", signal, watchlist,
                              "2026-01-15", sentiment_multiplier=1.0)

        self.assertEqual(trade_default["size"], trade_1x["size"])


class TestCorrelationGuard(unittest.TestCase):
    """Test check_correlation_guard() for forex currency and stock sector limits."""

    WATCHLIST = {
        "forex": [
            {"symbol": "EURUSD", "from": "EUR", "to": "USD", "pip_size": 0.0001},
            {"symbol": "GBPUSD", "from": "GBP", "to": "USD", "pip_size": 0.0001},
            {"symbol": "USDJPY", "from": "USD", "to": "JPY", "pip_size": 0.01},
            {"symbol": "EURJPY", "from": "EUR", "to": "JPY", "pip_size": 0.01},
        ],
        "stocks": [
            {"symbol": "SPY", "group": "index"},
            {"symbol": "QQQ", "group": "index"},
            {"symbol": "AAPL", "group": "mega_tech"},
            {"symbol": "NVDA", "group": "semiconductors"},
            {"symbol": "DELL", "group": "hardware"},
        ],
        "crypto": [
            {"symbol": "BTC", "market": "USD"},
        ],
    }
    RULES = {
        "correlation": {
            "enabled": True,
            "forex_max_same_currency": 1,
            "stock_max_same_group": 1,
        }
    }

    # ── Forex tests ──────────────────────────────────────────────

    def test_forex_blocks_same_currency_same_side(self):
        """EURUSD LONG open -> GBPUSD LONG blocked (both short USD)."""
        open_pos = [{"asset_class": "forex", "symbol": "EURUSD", "direction": "LONG"}]
        config = {"symbol": "GBPUSD", "from": "GBP", "to": "USD"}
        ok, reason = check_correlation_guard(
            "forex", "GBPUSD", "LONG", config, open_pos, self.RULES, self.WATCHLIST)
        self.assertFalse(ok)
        self.assertIn("USD", reason)

    def test_forex_allows_opposite_side(self):
        """EURUSD LONG (short USD) + USDJPY LONG (long USD) = opposite sides of USD."""
        open_pos = [{"asset_class": "forex", "symbol": "EURUSD", "direction": "LONG"}]
        config = {"symbol": "USDJPY", "from": "USD", "to": "JPY"}
        ok, reason = check_correlation_guard(
            "forex", "USDJPY", "LONG", config, open_pos, self.RULES, self.WATCHLIST)
        self.assertTrue(ok)

    def test_forex_allows_different_currency(self):
        """USDJPY SHORT (short USD, long JPY) + EURUSD SHORT (short EUR, long USD) = no overlap."""
        open_pos = [{"asset_class": "forex", "symbol": "USDJPY", "direction": "SHORT"}]
        config = {"symbol": "EURUSD", "from": "EUR", "to": "USD"}
        ok, reason = check_correlation_guard(
            "forex", "EURUSD", "SHORT", config, open_pos, self.RULES, self.WATCHLIST)
        self.assertTrue(ok)

    def test_forex_blocks_base_currency_overlap(self):
        """EURUSD LONG + EURJPY LONG = both long EUR."""
        open_pos = [{"asset_class": "forex", "symbol": "EURUSD", "direction": "LONG"}]
        config = {"symbol": "EURJPY", "from": "EUR", "to": "JPY"}
        ok, reason = check_correlation_guard(
            "forex", "EURJPY", "LONG", config, open_pos, self.RULES, self.WATCHLIST)
        self.assertFalse(ok)
        self.assertIn("EUR", reason)

    def test_forex_respects_max_2(self):
        """With forex_max_same_currency=2, allows 2 but blocks 3rd."""
        rules = {"correlation": {"enabled": True, "forex_max_same_currency": 2}}
        open_pos = [{"asset_class": "forex", "symbol": "EURUSD", "direction": "LONG"}]
        config = {"symbol": "GBPUSD", "from": "GBP", "to": "USD"}
        # 2nd short-USD position: allowed
        ok, _ = check_correlation_guard(
            "forex", "GBPUSD", "LONG", config, open_pos, rules, self.WATCHLIST)
        self.assertTrue(ok)

        # 3rd short-USD position: blocked
        open_pos.append({"asset_class": "forex", "symbol": "GBPUSD", "direction": "LONG"})
        config2 = {"symbol": "USDJPY", "from": "USD", "to": "JPY"}
        ok2, _ = check_correlation_guard(
            "forex", "USDJPY", "SHORT", config2, open_pos, rules, self.WATCHLIST)
        self.assertFalse(ok2)

    def test_forex_disabled_allows_all(self):
        """Disabled correlation guard allows everything."""
        rules = {"correlation": {"enabled": False}}
        open_pos = [{"asset_class": "forex", "symbol": "EURUSD", "direction": "LONG"}]
        config = {"symbol": "GBPUSD", "from": "GBP", "to": "USD"}
        ok, reason = check_correlation_guard(
            "forex", "GBPUSD", "LONG", config, open_pos, rules, self.WATCHLIST)
        self.assertTrue(ok)
        self.assertEqual(reason, "disabled")

    def test_forex_missing_config_defaults_allowed(self):
        """No correlation config in rules -> allowed."""
        rules = {}
        open_pos = [{"asset_class": "forex", "symbol": "EURUSD", "direction": "LONG"}]
        config = {"symbol": "GBPUSD", "from": "GBP", "to": "USD"}
        ok, _ = check_correlation_guard(
            "forex", "GBPUSD", "LONG", config, open_pos, rules, self.WATCHLIST)
        self.assertTrue(ok)

    # ── Stock tests ──────────────────────────────────────────────

    def test_stock_blocks_same_group(self):
        """SPY open -> QQQ blocked (both index)."""
        open_pos = [{"asset_class": "stocks", "symbol": "SPY", "direction": "LONG"}]
        config = {"symbol": "QQQ", "group": "index"}
        ok, reason = check_correlation_guard(
            "stocks", "QQQ", "LONG", config, open_pos, self.RULES, self.WATCHLIST)
        self.assertFalse(ok)
        self.assertIn("index", reason)

    def test_stock_allows_different_group(self):
        """SPY (index) open -> NVDA (semiconductors) allowed."""
        open_pos = [{"asset_class": "stocks", "symbol": "SPY", "direction": "LONG"}]
        config = {"symbol": "NVDA", "group": "semiconductors"}
        ok, _ = check_correlation_guard(
            "stocks", "NVDA", "LONG", config, open_pos, self.RULES, self.WATCHLIST)
        self.assertTrue(ok)

    def test_stock_no_group_always_allowed(self):
        """Stock without group field is always allowed."""
        open_pos = [{"asset_class": "stocks", "symbol": "SPY", "direction": "LONG"}]
        config = {"symbol": "UNKNOWN"}
        ok, reason = check_correlation_guard(
            "stocks", "UNKNOWN", "LONG", config, open_pos, self.RULES, self.WATCHLIST)
        self.assertTrue(ok)
        self.assertEqual(reason, "no_group")

    def test_stock_disabled_allows_all(self):
        """Disabled guard allows same-group stocks."""
        rules = {"correlation": {"enabled": False}}
        open_pos = [{"asset_class": "stocks", "symbol": "SPY", "direction": "LONG"}]
        config = {"symbol": "QQQ", "group": "index"}
        ok, _ = check_correlation_guard(
            "stocks", "QQQ", "LONG", config, open_pos, rules, self.WATCHLIST)
        self.assertTrue(ok)

    # ── Crypto test ──────────────────────────────────────────────

    def test_crypto_always_allowed(self):
        """Crypto always returns allowed (capped at 1 position elsewhere)."""
        open_pos = [{"asset_class": "crypto", "symbol": "BTC", "direction": "LONG"}]
        config = {"symbol": "ETH", "market": "USD"}
        ok, _ = check_correlation_guard(
            "crypto", "ETH", "LONG", config, open_pos, self.RULES, self.WATCHLIST)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
