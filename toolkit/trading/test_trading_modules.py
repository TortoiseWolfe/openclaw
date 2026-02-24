#!/usr/bin/env python3
"""Isolation unit tests for trading_common, trading_signals, and trading_output.

Tests pure functions from the three shared trading modules using unittest.
File I/O is mocked (@patch) for functions that read from fixed paths,
and tempfile.TemporaryDirectory is used for functions that write to
configurable paths.
"""

import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import patch, mock_open

from trading_common import (
    validate_candle, validate_candles, classify_signal,
    check_correlation_guard, atomic_json_write, load_sentiment_for_trading,
)
from trading_signals import (
    compute_sentiment_multiplier, compute_sma,
    load_education_progress,
)
from trading_output import (
    write_paper_md, append_journal, cleanup_old_analyses,
)


# ══════════════════════════════════════════════════════════════════════
#  trading_common.py tests
# ══════════════════════════════════════════════════════════════════════


class TestValidateCandle(unittest.TestCase):
    """Test validate_candle() for single candle validation."""

    def test_valid_candle_passes(self):
        ok, reason = validate_candle({"o": 100, "h": 105, "l": 95, "c": 102})
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_zero_open_fails(self):
        ok, reason = validate_candle({"o": 0, "h": 105, "l": 95, "c": 102})
        self.assertFalse(ok)
        self.assertIn("zero", reason)

    def test_zero_high_fails(self):
        ok, reason = validate_candle({"o": 100, "h": 0, "l": 95, "c": 102})
        self.assertFalse(ok)
        self.assertIn("zero", reason)

    def test_zero_low_fails(self):
        ok, reason = validate_candle({"o": 100, "h": 105, "l": 0, "c": 102})
        self.assertFalse(ok)
        self.assertIn("zero", reason)

    def test_zero_close_fails(self):
        ok, reason = validate_candle({"o": 100, "h": 105, "l": 95, "c": 0})
        self.assertFalse(ok)
        self.assertIn("zero", reason)

    def test_negative_value_fails(self):
        ok, reason = validate_candle({"o": -5, "h": 105, "l": 95, "c": 102})
        self.assertFalse(ok)
        self.assertIn("zero", reason)

    def test_high_below_close_fails(self):
        """high < max(open, close) is a reversed wick."""
        ok, reason = validate_candle({"o": 100, "h": 99, "l": 95, "c": 102})
        self.assertFalse(ok)
        self.assertIn("high", reason)

    def test_high_below_open_fails(self):
        ok, reason = validate_candle({"o": 103, "h": 101, "l": 95, "c": 100})
        self.assertFalse(ok)
        self.assertIn("high", reason)

    def test_low_above_open_fails(self):
        """low > min(open, close) is a reversed wick."""
        ok, reason = validate_candle({"o": 100, "h": 105, "l": 101, "c": 102})
        self.assertFalse(ok)
        self.assertIn("low", reason)

    def test_low_above_close_fails(self):
        ok, reason = validate_candle({"o": 102, "h": 105, "l": 101, "c": 100})
        self.assertFalse(ok)
        self.assertIn("low", reason)

    def test_missing_keys_default_to_zero_and_fail(self):
        """Missing OHLC keys .get() defaults to 0, which fails validation."""
        ok, reason = validate_candle({"h": 105, "l": 95, "c": 102})
        self.assertFalse(ok)

    def test_all_keys_missing_fails(self):
        ok, reason = validate_candle({})
        self.assertFalse(ok)

    def test_doji_candle_passes(self):
        """Doji: open == close, still valid if wicks are correct."""
        ok, reason = validate_candle({"o": 100, "h": 102, "l": 98, "c": 100})
        self.assertTrue(ok)
        self.assertIsNone(reason)


class TestValidateCandles(unittest.TestCase):
    """Test validate_candles() for batch validation and filtering."""

    def test_filters_invalid_keeps_valid(self):
        candles = [
            {"o": 100, "h": 105, "l": 95, "c": 102},   # valid
            {"o": 0, "h": 105, "l": 95, "c": 102},      # zero open
            {"o": 100, "h": 99, "l": 95, "c": 102},     # high < close
            {"o": 50, "h": 55, "l": 45, "c": 52},       # valid
        ]
        result = validate_candles(candles, symbol="TEST")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["o"], 100)
        self.assertEqual(result[1]["o"], 50)

    def test_all_valid_returns_all(self):
        candles = [
            {"o": 100, "h": 105, "l": 95, "c": 102},
            {"o": 50, "h": 55, "l": 45, "c": 52},
        ]
        result = validate_candles(candles)
        self.assertEqual(len(result), 2)

    def test_all_invalid_returns_empty(self):
        candles = [
            {"o": 0, "h": 0, "l": 0, "c": 0},
            {"o": -1, "h": 5, "l": 3, "c": 4},
        ]
        result = validate_candles(candles)
        self.assertEqual(len(result), 0)

    def test_empty_list_returns_empty(self):
        result = validate_candles([])
        self.assertEqual(result, [])


class TestClassifySignal(unittest.TestCase):
    """Test classify_signal() reason-to-type mapping."""

    def test_uptrend_returns_trend(self):
        self.assertEqual(classify_signal("uptrend (HH:5/9)"), "trend")

    def test_downtrend_returns_trend(self):
        self.assertEqual(classify_signal("downtrend (LL:4/9)"), "trend")

    def test_sma_bullish_returns_sma(self):
        self.assertEqual(classify_signal("SMA5>SMA20 (bullish)"), "sma")

    def test_sma_bearish_returns_sma(self):
        self.assertEqual(classify_signal("SMA5<SMA20 (bearish)"), "sma")

    def test_ranging_pattern_returns_pattern(self):
        self.assertEqual(classify_signal("ranging + bullish pin bar"), "pattern")

    def test_ranging_engulfing_returns_pattern(self):
        self.assertEqual(classify_signal("ranging + bearish engulfing"), "pattern")

    def test_near_support_returns_range_position(self):
        self.assertEqual(
            classify_signal("ranging, near support (15%)"), "range_position")

    def test_near_resistance_returns_range_position(self):
        self.assertEqual(
            classify_signal("ranging, near resistance (85%)"), "range_position")

    def test_yolo_returns_yolo(self):
        self.assertEqual(classify_signal("yolo something"), "yolo")

    def test_last_candle_returns_yolo(self):
        self.assertEqual(classify_signal("last candle action"), "yolo")

    def test_unknown_reason_returns_unknown(self):
        self.assertEqual(classify_signal("some random reason"), "unknown")

    def test_empty_string_returns_unknown(self):
        self.assertEqual(classify_signal(""), "unknown")

    def test_case_insensitive(self):
        """classify_signal lowercases before matching."""
        self.assertEqual(classify_signal("UPTREND (HH:5/9)"), "trend")
        self.assertEqual(classify_signal("Ranging + Bullish pin bar"), "pattern")


class TestCheckCorrelationGuard(unittest.TestCase):
    """Test check_correlation_guard() for forex, stocks, and crypto."""

    WATCHLIST = {
        "forex": [
            {"symbol": "EURUSD", "from": "EUR", "to": "USD", "pip_size": 0.0001},
            {"symbol": "GBPUSD", "from": "GBP", "to": "USD", "pip_size": 0.0001},
            {"symbol": "USDJPY", "from": "USD", "to": "JPY", "pip_size": 0.01},
        ],
        "stocks": [
            {"symbol": "SPY", "group": "index"},
            {"symbol": "QQQ", "group": "index"},
            {"symbol": "AAPL", "group": "mega_tech"},
            {"symbol": "NVDA", "group": "semiconductors"},
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

    # ── Forex ────────────────────────────────────────────────

    def test_forex_same_currency_blocks_at_limit(self):
        """EURUSD LONG open -> GBPUSD LONG blocked (both short USD at limit)."""
        open_pos = [{"asset_class": "forex", "symbol": "EURUSD", "direction": "LONG"}]
        config = {"symbol": "GBPUSD", "from": "GBP", "to": "USD"}
        ok, reason = check_correlation_guard(
            "forex", "GBPUSD", "LONG", config, open_pos, self.RULES, self.WATCHLIST)
        self.assertFalse(ok)
        self.assertIn("USD", reason)

    def test_forex_different_currencies_allowed(self):
        """USDJPY SHORT + EURUSD SHORT = no overlapping exposure."""
        open_pos = [{"asset_class": "forex", "symbol": "USDJPY", "direction": "SHORT"}]
        config = {"symbol": "EURUSD", "from": "EUR", "to": "USD"}
        ok, reason = check_correlation_guard(
            "forex", "EURUSD", "SHORT", config, open_pos, self.RULES, self.WATCHLIST)
        self.assertTrue(ok)

    def test_forex_opposite_sides_allowed(self):
        """EURUSD LONG (short USD) + USDJPY LONG (long USD) = opposite sides."""
        open_pos = [{"asset_class": "forex", "symbol": "EURUSD", "direction": "LONG"}]
        config = {"symbol": "USDJPY", "from": "USD", "to": "JPY"}
        ok, reason = check_correlation_guard(
            "forex", "USDJPY", "LONG", config, open_pos, self.RULES, self.WATCHLIST)
        self.assertTrue(ok)

    # ── Stocks ───────────────────────────────────────────────

    def test_stock_same_group_blocks_at_limit(self):
        """SPY open -> QQQ blocked (both 'index')."""
        open_pos = [{"asset_class": "stocks", "symbol": "SPY", "direction": "LONG"}]
        config = {"symbol": "QQQ", "group": "index"}
        ok, reason = check_correlation_guard(
            "stocks", "QQQ", "LONG", config, open_pos, self.RULES, self.WATCHLIST)
        self.assertFalse(ok)
        self.assertIn("index", reason)

    def test_stock_different_group_allowed(self):
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

    # ── Crypto ───────────────────────────────────────────────

    def test_crypto_always_allowed(self):
        """Crypto always returns allowed."""
        open_pos = [{"asset_class": "crypto", "symbol": "BTC", "direction": "LONG"}]
        config = {"symbol": "ETH", "market": "USD"}
        ok, _ = check_correlation_guard(
            "crypto", "ETH", "LONG", config, open_pos, self.RULES, self.WATCHLIST)
        self.assertTrue(ok)

    # ── Disabled guard ───────────────────────────────────────

    def test_disabled_guard_returns_true(self):
        rules = {"correlation": {"enabled": False}}
        open_pos = [{"asset_class": "forex", "symbol": "EURUSD", "direction": "LONG"}]
        config = {"symbol": "GBPUSD", "from": "GBP", "to": "USD"}
        ok, reason = check_correlation_guard(
            "forex", "GBPUSD", "LONG", config, open_pos, rules, self.WATCHLIST)
        self.assertTrue(ok)
        self.assertEqual(reason, "disabled")

    def test_missing_correlation_config_returns_true(self):
        ok, _ = check_correlation_guard(
            "forex", "GBPUSD", "LONG",
            {"symbol": "GBPUSD", "from": "GBP", "to": "USD"},
            [{"asset_class": "forex", "symbol": "EURUSD", "direction": "LONG"}],
            {}, self.WATCHLIST)
        self.assertTrue(ok)


class TestAtomicJsonWrite(unittest.TestCase):
    """Test atomic_json_write() file writing."""

    def test_writes_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.json")
            data = {"key": "value", "count": 42}
            atomic_json_write(path, data)
            with open(path) as f:
                loaded = json.load(f)
            self.assertEqual(loaded, data)

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "nested", "deep", "test.json")
            data = {"nested": True}
            atomic_json_write(path, data)
            self.assertTrue(os.path.exists(path))
            with open(path) as f:
                loaded = json.load(f)
            self.assertEqual(loaded, data)

    def test_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.json")
            atomic_json_write(path, {"version": 1})
            atomic_json_write(path, {"version": 2})
            with open(path) as f:
                loaded = json.load(f)
            self.assertEqual(loaded["version"], 2)

    def test_custom_indent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.json")
            atomic_json_write(path, {"a": 1}, indent=4)
            with open(path) as f:
                content = f.read()
            # 4-space indent
            self.assertIn("    ", content)

    def test_no_temp_file_left_behind(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.json")
            atomic_json_write(path, {"clean": True})
            files = os.listdir(tmpdir)
            self.assertEqual(files, ["test.json"])


class TestLoadSentimentForTrading(unittest.TestCase):
    """Test load_sentiment_for_trading() data loading."""

    SENTIMENT_DATA = {
        "forex_pairs": {
            "EURUSD": {"net_sentiment": 0.15},
            "GBPUSD": {"net_sentiment": -0.3},
        },
        "symbols": {
            "AAPL": {"avg_sentiment": 0.4, "article_count": 5},
            "NVDA": {"avg_sentiment": -0.2, "article_count": 3},
            "CRYPTO:BTC": {"avg_sentiment": 0.6, "article_count": 2},
            "FOREX:EUR": {"avg_sentiment": 0.1, "article_count": 1},
            "EMPTY": {"avg_sentiment": 0.5, "article_count": 0},
        },
    }

    @patch("trading_common.open",
           new_callable=mock_open,
           read_data=None)
    def test_forex_net_sentiment(self, mock_f):
        mock_f.return_value.read.return_value = json.dumps(self.SENTIMENT_DATA)
        mock_f.return_value.__enter__ = lambda s: s
        mock_f.return_value.__exit__ = lambda s, *a: None

        # Use a direct approach: patch at the json.load level
        with patch("trading_common.open", mock_open(read_data=json.dumps(self.SENTIMENT_DATA))):
            with patch("json.load", return_value=self.SENTIMENT_DATA):
                scores = load_sentiment_for_trading("2026-02-18")

        self.assertAlmostEqual(scores["EURUSD"], 0.15)
        self.assertAlmostEqual(scores["GBPUSD"], -0.3)

    @patch("trading_common.open", side_effect=FileNotFoundError)
    def test_missing_file_returns_empty(self, mock_f):
        scores = load_sentiment_for_trading("2026-02-18")
        self.assertEqual(scores, {})

    def test_stock_direct_sentiment(self):
        """Stocks get direct avg_sentiment score."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "sentiment-2026-02-18.json")
            with open(path, "w") as f:
                json.dump(self.SENTIMENT_DATA, f)

            with patch("trading_common.NEWS_DIR", tmpdir):
                scores = load_sentiment_for_trading("2026-02-18")

        self.assertAlmostEqual(scores["AAPL"], 0.4)
        self.assertAlmostEqual(scores["NVDA"], -0.2)

    def test_crypto_prefix_stripping(self):
        """CRYPTO: prefix is stripped from symbol keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "sentiment-2026-02-18.json")
            with open(path, "w") as f:
                json.dump(self.SENTIMENT_DATA, f)

            with patch("trading_common.NEWS_DIR", tmpdir):
                scores = load_sentiment_for_trading("2026-02-18")

        self.assertIn("BTC", scores)
        self.assertNotIn("CRYPTO:BTC", scores)
        self.assertAlmostEqual(scores["BTC"], 0.6)

    def test_forex_prefix_excluded_from_symbols(self):
        """FOREX: prefixed symbols are excluded (forex uses pairs, not currencies)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "sentiment-2026-02-18.json")
            with open(path, "w") as f:
                json.dump(self.SENTIMENT_DATA, f)

            with patch("trading_common.NEWS_DIR", tmpdir):
                scores = load_sentiment_for_trading("2026-02-18")

        self.assertNotIn("FOREX:EUR", scores)
        self.assertNotIn("EUR", scores)

    def test_zero_article_count_excluded(self):
        """Symbols with article_count=0 are excluded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "sentiment-2026-02-18.json")
            with open(path, "w") as f:
                json.dump(self.SENTIMENT_DATA, f)

            with patch("trading_common.NEWS_DIR", tmpdir):
                scores = load_sentiment_for_trading("2026-02-18")

        self.assertNotIn("EMPTY", scores)

    def test_corrupt_json_returns_empty(self):
        """Malformed JSON returns empty dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "sentiment-2026-02-18.json")
            with open(path, "w") as f:
                f.write("{bad json")

            with patch("trading_common.NEWS_DIR", tmpdir):
                scores = load_sentiment_for_trading("2026-02-18")

        self.assertEqual(scores, {})


# ══════════════════════════════════════════════════════════════════════
#  trading_signals.py tests
# ══════════════════════════════════════════════════════════════════════


class TestComputeSentimentMultiplier(unittest.TestCase):
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

    def test_no_sentiment_config_returns_1(self):
        mult, reason = compute_sentiment_multiplier("AAPL", "LONG", {"AAPL": 0.5}, {})
        self.assertEqual(mult, 1.0)
        self.assertEqual(reason, "disabled")

    def test_no_data_returns_1(self):
        mult, reason = compute_sentiment_multiplier("AAPL", "LONG", {}, self.RULES)
        self.assertEqual(mult, 1.0)
        self.assertEqual(reason, "no_data")

    def test_symbol_not_in_scores_returns_1(self):
        mult, reason = compute_sentiment_multiplier("AAPL", "LONG", {"NVDA": 0.5}, self.RULES)
        self.assertEqual(mult, 1.0)
        self.assertEqual(reason, "no_data")

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

    def test_long_disagrees_returns_disagree_multiplier(self):
        mult, reason = compute_sentiment_multiplier(
            "AAPL", "LONG", {"AAPL": -0.2}, self.RULES)
        self.assertEqual(mult, 0.5)
        self.assertEqual(reason, "disagree")

    def test_short_disagrees_returns_disagree_multiplier(self):
        mult, reason = compute_sentiment_multiplier(
            "AAPL", "SHORT", {"AAPL": 0.2}, self.RULES)
        self.assertEqual(mult, 0.5)
        self.assertEqual(reason, "disagree")

    def test_strong_disagree_skip_returns_zero(self):
        """Strong disagreement with skip action returns 0.0 (veto)."""
        mult, reason = compute_sentiment_multiplier(
            "AAPL", "LONG", {"AAPL": -0.4}, self.RULES)
        self.assertEqual(mult, 0.0)
        self.assertEqual(reason, "strong_disagree")

    def test_strong_disagree_dampen_returns_disagree_multiplier(self):
        """Strong disagreement with dampen action returns disagree_multiplier."""
        rules = {
            "sentiment": {
                "enabled": True,
                "agree_multiplier": 1.0,
                "disagree_multiplier": 0.5,
                "strong_disagree_threshold": 0.3,
                "strong_disagree_action": "dampen",
            }
        }
        mult, reason = compute_sentiment_multiplier(
            "AAPL", "LONG", {"AAPL": -0.4}, rules)
        self.assertEqual(mult, 0.5)
        self.assertEqual(reason, "strong_disagree")

    def test_zero_sentiment_agrees_with_long(self):
        """Score of 0.0 is treated as agreeing (neutral >= 0)."""
        mult, reason = compute_sentiment_multiplier(
            "AAPL", "LONG", {"AAPL": 0.0}, self.RULES)
        self.assertEqual(mult, 1.0)
        self.assertEqual(reason, "agree")

    def test_zero_sentiment_agrees_with_short(self):
        """Score of 0.0 is treated as agreeing for SHORT too (0 <= 0)."""
        mult, reason = compute_sentiment_multiplier(
            "AAPL", "SHORT", {"AAPL": 0.0}, self.RULES)
        self.assertEqual(mult, 1.0)
        self.assertEqual(reason, "agree")

    def test_exactly_at_threshold_is_strong(self):
        """Score at exactly the threshold triggers strong_disagree."""
        mult, reason = compute_sentiment_multiplier(
            "AAPL", "LONG", {"AAPL": -0.3}, self.RULES)
        self.assertEqual(mult, 0.0)
        self.assertEqual(reason, "strong_disagree")


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

    def test_exact_period_length(self):
        """Exactly enough candles should compute correctly."""
        candles = [{"c": 5}, {"c": 10}, {"c": 15}, {"c": 20}, {"c": 25}]
        self.assertAlmostEqual(compute_sma(candles, 5), 15.0)

    def test_period_one(self):
        candles = [{"c": 42}]
        self.assertAlmostEqual(compute_sma(candles, 1), 42.0)

    def test_all_same_values(self):
        candles = [{"c": 100}] * 10
        self.assertAlmostEqual(compute_sma(candles, 5), 100.0)


class TestEducationProgress(unittest.TestCase):
    """Test load_education_progress() markdown table parsing."""

    SAMPLE_CURRICULUM = """\
# BabyPips Curriculum Progress

| # | Section | Lesson | Link | Status |
|---|---------|--------|------|--------|
| 1 | Japanese Candlesticks | Basic Candlestick Patterns | http://example.com | done |
| 2 | Japanese Candlesticks | Advanced Patterns | http://example.com | done |
| 3 | Moving Averages | SMA Basics | http://example.com | done |
| 4 | Moving Averages | EMA Basics | http://example.com | in-progress |
| 5 | Support and Resistance Levels | S/R Intro | http://example.com | not-started |
"""

    @patch("trading_signals.CURRICULUM", "/fake/path/curriculum-progress.md")
    def test_parse_markdown_table(self):
        with patch("builtins.open", mock_open(read_data=self.SAMPLE_CURRICULUM)):
            sections, done, total = load_education_progress()

        # Japanese Candlesticks: 2/2 done -> completed
        self.assertIn("Japanese Candlesticks", sections)
        # Moving Averages: 1/2 done -> NOT completed
        self.assertNotIn("Moving Averages", sections)
        # S&R: 0/1 -> NOT completed
        self.assertNotIn("Support and Resistance Levels", sections)

    @patch("trading_signals.CURRICULUM", "/fake/path/curriculum-progress.md")
    def test_count_sections(self):
        with patch("builtins.open", mock_open(read_data=self.SAMPLE_CURRICULUM)):
            sections, done, total = load_education_progress()

        self.assertEqual(total, 5)
        self.assertEqual(done, 3)

    @patch("trading_signals.CURRICULUM", "/fake/path/curriculum-progress.md")
    def test_missing_file_returns_empty(self):
        with patch("builtins.open", side_effect=FileNotFoundError):
            sections, done, total = load_education_progress()

        self.assertEqual(sections, set())
        self.assertEqual(done, 0)
        self.assertEqual(total, 0)

    @patch("trading_signals.CURRICULUM", "/fake/path/curriculum-progress.md")
    def test_all_done_section(self):
        content = """\
| 1 | Fibonacci | Fib Levels | http://example.com | done |
| 2 | Fibonacci | Fib Extensions | http://example.com | done |
"""
        with patch("builtins.open", mock_open(read_data=content)):
            sections, done, total = load_education_progress()

        self.assertIn("Fibonacci", sections)
        self.assertEqual(done, 2)
        self.assertEqual(total, 2)


# ══════════════════════════════════════════════════════════════════════
#  trading_output.py tests
# ══════════════════════════════════════════════════════════════════════


class TestWritePaperMd(unittest.TestCase):
    """Test write_paper_md() markdown generation."""

    def _make_state(self, open_positions=None, closed_positions=None, balance=10000.0):
        return {
            "open": open_positions or [],
            "closed": closed_positions or [],
            "balance": balance,
        }

    def test_generates_correct_sections(self):
        state = self._make_state(
            open_positions=[{
                "id": "T001", "date_opened": "2026-02-15",
                "asset_class": "stocks", "symbol": "AAPL",
                "direction": "LONG", "entry": 150.0,
                "stop_loss": 148.0, "take_profit": 156.0,
                "size": 50, "unrealized_pnl": 25.0,
            }],
            closed_positions=[{
                "id": "T000", "date_opened": "2026-02-10",
                "date_closed": "2026-02-14",
                "asset_class": "stocks", "symbol": "NVDA",
                "direction": "LONG", "entry": 800.0, "exit": 820.0,
                "size": 5, "pnl_dollars": 100.0,
                "close_reason": "take profit",
            }],
            balance=10100.0,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            paper_md_path = os.path.join(tmpdir, "paper-trades.md")
            with patch("trading_output.PAPER_MD", paper_md_path):
                write_paper_md(state, "BabyPips: 3/20 (15%)")

            self.assertTrue(os.path.exists(paper_md_path))
            with open(paper_md_path) as f:
                content = f.read()

        self.assertIn("# Paper Trades", content)
        self.assertIn("## Open Positions", content)
        self.assertIn("## Closed Positions", content)
        self.assertIn("## Running Statistics", content)
        self.assertIn("T001", content)
        self.assertIn("AAPL", content)
        self.assertIn("T000", content)
        self.assertIn("NVDA", content)
        self.assertIn("$10,100.00", content)
        self.assertIn("BabyPips: 3/20 (15%)", content)

    def test_empty_trades_shows_na_stats(self):
        state = self._make_state()

        with tempfile.TemporaryDirectory() as tmpdir:
            paper_md_path = os.path.join(tmpdir, "paper-trades.md")
            with patch("trading_output.PAPER_MD", paper_md_path):
                write_paper_md(state, "BabyPips: 0/0 (0%)")

            with open(paper_md_path) as f:
                content = f.read()

        self.assertIn("**Win rate:** N/A", content)
        self.assertIn("**Average win:** N/A", content)
        self.assertIn("**Average loss:** N/A", content)
        self.assertIn("**Best trade:** N/A", content)
        self.assertIn("**Worst trade:** N/A", content)
        self.assertIn("**Total P&L:** N/A", content)

    def test_win_rate_computed(self):
        """Win rate is correctly computed from closed positions."""
        closed = [
            {"id": f"T{i:03d}", "date_opened": "2026-02-01",
             "date_closed": "2026-02-10", "asset_class": "stocks",
             "symbol": "AAPL", "direction": "LONG",
             "entry": 100.0, "exit": 110.0, "size": 10,
             "pnl_dollars": 100.0 if i < 3 else -50.0,
             "close_reason": "take profit" if i < 3 else "stop loss"}
            for i in range(4)
        ]
        state = self._make_state(closed_positions=closed)

        with tempfile.TemporaryDirectory() as tmpdir:
            paper_md_path = os.path.join(tmpdir, "paper-trades.md")
            with patch("trading_output.PAPER_MD", paper_md_path):
                write_paper_md(state, "test")

            with open(paper_md_path) as f:
                content = f.read()

        # 3 wins / 4 trades = 75%
        self.assertIn("**Win rate:** 75%", content)


class TestAppendJournal(unittest.TestCase):
    """Test append_journal() journal entry writing."""

    def _make_analyses(self, n=3):
        return [{
            "asset_class": "stocks", "symbol": f"SYM{i}",
            "trend": "uptrend", "signal": {"direction": "LONG"}
            if i == 0 else None,
            "hh": 5, "hl": 4, "lh": 1, "ll": 0,
        } for i in range(n)]

    def _make_trade(self, tid="T001"):
        return {
            "id": tid, "asset_class": "stocks", "symbol": "AAPL",
            "direction": "LONG", "reason": "uptrend (HH:5/9)",
        }

    def _make_closed(self, tid="T000"):
        return {
            "id": tid, "asset_class": "stocks", "symbol": "NVDA",
            "direction": "LONG", "close_reason": "take profit",
            "pnl_dollars": 75.0,
        }

    def test_appends_entry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = os.path.join(tmpdir, "trade-journal.md")
            with patch("trading_output.JOURNAL", journal_path):
                append_journal(
                    self._make_analyses(), [self._make_trade()],
                    [self._make_closed()], 10075.0, "BabyPips: 5/20", "2026-02-18")

            self.assertTrue(os.path.exists(journal_path))
            with open(journal_path) as f:
                content = f.read()

        self.assertIn("### 2026-02-18 --- Automated Analysis", content.replace("\u2014", "---"))
        self.assertIn("**Assets analyzed**: 3", content)
        self.assertIn("**Trades opened**: 1", content)
        self.assertIn("**Trades closed**: 1", content)
        self.assertIn("**Balance**: $10,075.00", content)
        self.assertIn("T001", content)
        self.assertIn("T000", content)

    def test_deduplicates_same_day(self):
        """Calling append_journal twice for the same day writes only once."""
        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = os.path.join(tmpdir, "trade-journal.md")
            with patch("trading_output.JOURNAL", journal_path):
                append_journal(
                    self._make_analyses(), [], [], 10000.0, "test", "2026-02-18")
                append_journal(
                    self._make_analyses(), [], [], 10000.0, "test", "2026-02-18")

            with open(journal_path) as f:
                content = f.read()

        # Should only appear once
        occurrences = content.count("### 2026-02-18")
        self.assertEqual(occurrences, 1)

    def test_different_days_both_written(self):
        """Entries for different days are both appended."""
        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = os.path.join(tmpdir, "trade-journal.md")
            with patch("trading_output.JOURNAL", journal_path):
                append_journal(
                    self._make_analyses(), [], [], 10000.0, "test", "2026-02-18")
                append_journal(
                    self._make_analyses(), [], [], 10000.0, "test", "2026-02-19")

            with open(journal_path) as f:
                content = f.read()

        self.assertIn("### 2026-02-18", content)
        self.assertIn("### 2026-02-19", content)


class TestCleanupOldAnalyses(unittest.TestCase):
    """Test cleanup_old_analyses() file retention."""

    def test_deletes_old_files(self):
        today = date(2026, 2, 18)
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create old file (60 days ago)
            old_date = today - timedelta(days=60)
            old_file = os.path.join(tmpdir, f"daily-analysis-{old_date.isoformat()}.md")
            with open(old_file, "w") as f:
                f.write("old analysis")

            with patch("trading_output.PRIVATE_DIR", tmpdir):
                cleanup_old_analyses(today, retain_days=30)

            self.assertFalse(os.path.exists(old_file))

    def test_keeps_recent_files(self):
        today = date(2026, 2, 18)
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create recent file (5 days ago)
            recent_date = today - timedelta(days=5)
            recent_file = os.path.join(tmpdir, f"daily-analysis-{recent_date.isoformat()}.md")
            with open(recent_file, "w") as f:
                f.write("recent analysis")

            with patch("trading_output.PRIVATE_DIR", tmpdir):
                cleanup_old_analyses(today, retain_days=30)

            self.assertTrue(os.path.exists(recent_file))

    def test_keeps_file_at_exact_cutoff(self):
        """File exactly at retain_days boundary is kept (cutoff is exclusive)."""
        today = date(2026, 2, 18)
        with tempfile.TemporaryDirectory() as tmpdir:
            cutoff_date = today - timedelta(days=30)
            cutoff_file = os.path.join(tmpdir, f"daily-analysis-{cutoff_date.isoformat()}.md")
            with open(cutoff_file, "w") as f:
                f.write("boundary analysis")

            with patch("trading_output.PRIVATE_DIR", tmpdir):
                cleanup_old_analyses(today, retain_days=30)

            # cutoff = today - 30, file_date == cutoff, NOT < cutoff -> kept
            self.assertTrue(os.path.exists(cutoff_file))

    def test_mixed_old_and_recent(self):
        today = date(2026, 2, 18)
        with tempfile.TemporaryDirectory() as tmpdir:
            # Old file
            old_date = today - timedelta(days=45)
            old_file = os.path.join(tmpdir, f"daily-analysis-{old_date.isoformat()}.md")
            with open(old_file, "w") as f:
                f.write("old")

            # Recent file
            recent_date = today - timedelta(days=10)
            recent_file = os.path.join(tmpdir, f"daily-analysis-{recent_date.isoformat()}.md")
            with open(recent_file, "w") as f:
                f.write("recent")

            # Unrelated file (should not be touched)
            other_file = os.path.join(tmpdir, "paper-trades.md")
            with open(other_file, "w") as f:
                f.write("not an analysis")

            with patch("trading_output.PRIVATE_DIR", tmpdir):
                cleanup_old_analyses(today, retain_days=30)

            self.assertFalse(os.path.exists(old_file))
            self.assertTrue(os.path.exists(recent_file))
            self.assertTrue(os.path.exists(other_file))

    def test_empty_directory_no_error(self):
        today = date(2026, 2, 18)
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("trading_output.PRIVATE_DIR", tmpdir):
                # Should not raise
                cleanup_old_analyses(today, retain_days=30)


if __name__ == "__main__":
    unittest.main()
