#!/usr/bin/env python3
"""Tests for market_weekly_review.py — pure functions."""

import unittest
from datetime import date

from market_weekly_review import (
    week_bounds,
    filter_week,
    filter_closed_week,
    calc_stats,
    count_by_class,
    format_trade_line,
    build_review,
)


class TestWeekBounds(unittest.TestCase):
    def test_monday_returns_same_week(self):
        # 2026-02-02 is a Monday
        mon, sun = week_bounds(date(2026, 2, 2))
        self.assertEqual(mon, "2026-02-02")
        self.assertEqual(sun, "2026-02-08")

    def test_wednesday_returns_correct_bounds(self):
        # 2026-02-04 is a Wednesday
        mon, sun = week_bounds(date(2026, 2, 4))
        self.assertEqual(mon, "2026-02-02")
        self.assertEqual(sun, "2026-02-08")

    def test_sunday_returns_correct_bounds(self):
        # 2026-02-08 is a Sunday
        mon, sun = week_bounds(date(2026, 2, 8))
        self.assertEqual(mon, "2026-02-02")
        self.assertEqual(sun, "2026-02-08")


class TestFilterWeek(unittest.TestCase):
    def test_includes_trades_in_range(self):
        trades = [
            {"date_opened": "2026-02-03", "symbol": "EURUSD"},
            {"date_opened": "2026-02-10", "symbol": "AAPL"},
        ]
        result = filter_week(trades, "2026-02-02", "2026-02-08")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["symbol"], "EURUSD")

    def test_excludes_trades_outside_range(self):
        trades = [{"date_opened": "2026-01-15"}]
        result = filter_week(trades, "2026-02-02", "2026-02-08")
        self.assertEqual(result, [])

    def test_empty_list_returns_empty(self):
        self.assertEqual(filter_week([], "2026-02-02", "2026-02-08"), [])


class TestFilterClosedWeek(unittest.TestCase):
    def test_filters_by_date_closed(self):
        trades = [
            {"date_closed": "2026-02-03", "pnl_dollars": 50},
            {"date_closed": "2026-02-10", "pnl_dollars": -20},
        ]
        result = filter_closed_week(trades, "2026-02-02", "2026-02-08")
        self.assertEqual(len(result), 1)


class TestCalcStats(unittest.TestCase):
    def test_empty_list_returns_zeros(self):
        stats = calc_stats([])
        self.assertEqual(stats["wins"], 0)
        self.assertEqual(stats["losses"], 0)
        self.assertEqual(stats["total_pnl"], 0.0)

    def test_single_winning_trade(self):
        trades = [{"pnl_dollars": 100, "asset_class": "forex"}]
        stats = calc_stats(trades)
        self.assertEqual(stats["wins"], 1)
        self.assertEqual(stats["losses"], 0)
        self.assertAlmostEqual(stats["total_pnl"], 100.0)

    def test_single_losing_trade(self):
        trades = [{"pnl_dollars": -50, "asset_class": "stocks"}]
        stats = calc_stats(trades)
        self.assertEqual(stats["wins"], 0)
        self.assertEqual(stats["losses"], 1)

    def test_mixed_wins_losses(self):
        trades = [
            {"pnl_dollars": 100, "asset_class": "forex"},
            {"pnl_dollars": -30, "asset_class": "forex"},
            {"pnl_dollars": 50, "asset_class": "stocks"},
        ]
        stats = calc_stats(trades)
        self.assertEqual(stats["wins"], 2)
        self.assertEqual(stats["losses"], 1)
        self.assertAlmostEqual(stats["total_pnl"], 120.0)
        self.assertEqual(stats["best"]["pnl_dollars"], 100)
        self.assertEqual(stats["worst"]["pnl_dollars"], -30)

    def test_by_class_grouping(self):
        trades = [
            {"pnl_dollars": 100, "asset_class": "forex"},
            {"pnl_dollars": 50, "asset_class": "stocks"},
        ]
        stats = calc_stats(trades)
        self.assertEqual(stats["by_class"]["forex"]["count"], 1)
        self.assertEqual(stats["by_class"]["stocks"]["count"], 1)


class TestCountByClass(unittest.TestCase):
    def test_groups_by_asset_class(self):
        trades = [
            {"asset_class": "forex"},
            {"asset_class": "forex"},
            {"asset_class": "stocks"},
        ]
        counts = count_by_class(trades)
        self.assertEqual(counts["forex"], 2)
        self.assertEqual(counts["stocks"], 1)

    def test_empty_returns_empty(self):
        self.assertEqual(count_by_class([]), {})


class TestFormatTradeLine(unittest.TestCase):
    def test_formats_positive_pnl(self):
        trade = {"id": "T001", "symbol": "EURUSD", "direction": "LONG", "pnl_dollars": 50}
        result = format_trade_line(trade)
        self.assertIn("T001", result)
        self.assertIn("+50.00", result)

    def test_formats_negative_pnl(self):
        trade = {"id": "T002", "symbol": "AAPL", "direction": "SHORT", "pnl_dollars": -30}
        result = format_trade_line(trade)
        self.assertIn("-30.00", result)


class TestBuildReview(unittest.TestCase):
    def test_no_trades(self):
        state = {"balance": 10000.0, "open": [], "closed": []}
        lines = build_review(state, today=date(2026, 2, 6))
        text = "\n".join(lines)
        self.assertIn("Weekly Review", text)
        self.assertIn("Trades opened**: 0", text)
        self.assertIn("No signals met entry criteria", text)

    def test_with_closed_trades(self):
        state = {
            "balance": 10100.0,
            "open": [],
            "closed": [
                {
                    "date_opened": "2026-02-03",
                    "date_closed": "2026-02-05",
                    "pnl_dollars": 100,
                    "asset_class": "forex",
                    "id": "T001",
                    "symbol": "EURUSD",
                    "direction": "LONG",
                },
            ],
        }
        lines = build_review(state, today=date(2026, 2, 6))
        text = "\n".join(lines)
        self.assertIn("Trades closed**: 1", text)
        self.assertIn("100%", text)  # win rate
        self.assertIn("Positive week", text)


if __name__ == "__main__":
    unittest.main()
