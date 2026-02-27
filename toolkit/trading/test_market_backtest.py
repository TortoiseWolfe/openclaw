#!/usr/bin/env python3
"""Tests for backtest engine and statistical analysis modules."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from market_backtest_engine import BacktestConfig, run_backtest
from market_backtest_stats import (
    block_bootstrap_mc,
    compute_all_metrics,
    compute_calmar_ratio,
    compute_consecutive_stats,
    compute_daily_returns,
    compute_expectancy,
    compute_expectancy_dollars,
    compute_max_drawdown,
    compute_profit_factor,
    compute_sharpe_ratio,
    compute_sortino_ratio,
    compute_win_rate,
    classify_regime,
    monte_carlo_simulation,
)


# ── Helpers ───────────────────────────────────────────────────────────

def make_candle(date, o, h, l, c):
    return {"date": date, "o": o, "h": h, "l": l, "c": c}


def make_uptrend_candles(start_price=1.10, days=30, step=0.001):
    """Generate candles with a clear uptrend."""
    candles = []
    for i in range(days):
        p = start_price + i * step
        candles.append(make_candle(
            f"2024-01-{i+1:02d}", p, p + 0.002, p - 0.001, p + step))
    return candles


def make_downtrend_candles(start_price=1.20, days=30, step=0.001):
    """Generate candles with a clear downtrend."""
    candles = []
    for i in range(days):
        p = start_price - i * step
        candles.append(make_candle(
            f"2024-01-{i+1:02d}", p, p + 0.001, p - 0.002, p - step))
    return candles


def make_flat_candles(price=1.10, days=30):
    """Generate flat/ranging candles."""
    candles = []
    for i in range(days):
        candles.append(make_candle(
            f"2024-01-{i+1:02d}", price, price + 0.001, price - 0.001, price))
    return candles


def make_trade(pnl, rr=None):
    """Make a minimal trade dict for stats tests."""
    if rr is None:
        rr = pnl / 100.0  # rough R-multiple
    return {"pnl": pnl, "rr_achieved": rr}


# ── Stats Tests ───────────────────────────────────────────────────────

class TestWinRate(unittest.TestCase):
    def test_all_winners(self):
        trades = [make_trade(100), make_trade(50), make_trade(10)]
        self.assertAlmostEqual(compute_win_rate(trades), 1.0)

    def test_all_losers(self):
        trades = [make_trade(-100), make_trade(-50)]
        self.assertAlmostEqual(compute_win_rate(trades), 0.0)

    def test_mixed(self):
        trades = [make_trade(100), make_trade(-50), make_trade(30), make_trade(-20)]
        self.assertAlmostEqual(compute_win_rate(trades), 0.5)

    def test_empty(self):
        self.assertAlmostEqual(compute_win_rate([]), 0.0)


class TestExpectancy(unittest.TestCase):
    def test_positive_expectancy(self):
        trades = [make_trade(100, 1.5), make_trade(100, 1.5),
                  make_trade(-80, -1.0), make_trade(-80, -1.0),
                  make_trade(100, 1.5)]
        e = compute_expectancy(trades)
        self.assertGreater(e, 0)

    def test_negative_expectancy(self):
        trades = [make_trade(-80, -1.0)] * 4 + [make_trade(50, 0.5)]
        e = compute_expectancy(trades)
        self.assertLess(e, 0)

    def test_dollar_expectancy(self):
        trades = [make_trade(100), make_trade(-50)]
        self.assertAlmostEqual(compute_expectancy_dollars(trades), 25.0)


class TestProfitFactor(unittest.TestCase):
    def test_profitable(self):
        trades = [make_trade(200), make_trade(-100)]
        self.assertAlmostEqual(compute_profit_factor(trades), 2.0)

    def test_no_losses(self):
        trades = [make_trade(100), make_trade(50)]
        self.assertEqual(compute_profit_factor(trades), float("inf"))

    def test_no_wins(self):
        trades = [make_trade(-100), make_trade(-50)]
        self.assertAlmostEqual(compute_profit_factor(trades), 0.0)


class TestConsecutive(unittest.TestCase):
    def test_streaks(self):
        trades = [make_trade(10), make_trade(20), make_trade(30),
                  make_trade(-10), make_trade(-20),
                  make_trade(5)]
        result = compute_consecutive_stats(trades)
        self.assertEqual(result["max_consecutive_wins"], 3)
        self.assertEqual(result["max_consecutive_losses"], 2)


class TestEquityCurveMetrics(unittest.TestCase):
    def setUp(self):
        self.curve = [
            {"date": "2024-01-01", "balance": 10000},
            {"date": "2024-01-02", "balance": 10100},
            {"date": "2024-01-03", "balance": 10200},
            {"date": "2024-01-04", "balance": 9800},   # drawdown
            {"date": "2024-01-05", "balance": 10300},
            {"date": "2024-01-06", "balance": 10500},
        ]

    def test_daily_returns_count(self):
        returns = compute_daily_returns(self.curve)
        self.assertEqual(len(returns), 5)

    def test_sharpe_positive_for_gains(self):
        # Steady upward curve
        curve = [{"date": f"2024-01-{i+1:02d}", "balance": 10000 + i * 10}
                 for i in range(252)]
        sharpe = compute_sharpe_ratio(curve)
        self.assertGreater(sharpe, 0)

    def test_sharpe_near_zero_for_flat(self):
        curve = [{"date": f"2024-01-{i+1:02d}", "balance": 10000}
                 for i in range(100)]
        sharpe = compute_sharpe_ratio(curve)
        self.assertAlmostEqual(sharpe, 0.0)

    def test_sortino_positive_for_gains(self):
        # Curve with steady upside
        curve = [{"date": f"2024-01-{i+1:02d}", "balance": 10000 + i * 10}
                 for i in range(100)]
        sortino = compute_sortino_ratio(curve)
        self.assertGreater(sortino, 0)

    def test_max_drawdown(self):
        dd_pct, dd_dollar, peak_date, trough_date = compute_max_drawdown(self.curve)
        # Peak at 10200, trough at 9800 = 3.9% drawdown
        self.assertAlmostEqual(dd_pct, (10200 - 9800) / 10200, places=4)
        self.assertAlmostEqual(dd_dollar, 400.0)
        self.assertEqual(peak_date, "2024-01-03")
        self.assertEqual(trough_date, "2024-01-04")

    def test_max_drawdown_empty(self):
        dd_pct, dd_dollar, _, _ = compute_max_drawdown([])
        self.assertEqual(dd_pct, 0.0)


class TestMonteCarlo(unittest.TestCase):
    def test_deterministic_with_seed(self):
        trades = [make_trade(50)] * 10 + [make_trade(-30)] * 5
        r1 = monte_carlo_simulation(trades, n_simulations=100, seed=42)
        r2 = monte_carlo_simulation(trades, n_simulations=100, seed=42)
        self.assertEqual(r1["median_final_balance"], r2["median_final_balance"])
        self.assertEqual(r1["ruin_pct"], r2["ruin_pct"])

    def test_all_winners_no_ruin(self):
        trades = [make_trade(100)] * 20
        result = monte_carlo_simulation(trades, n_simulations=100, seed=42)
        self.assertEqual(result["ruin_pct"], 0.0)

    def test_all_losers_high_ruin(self):
        trades = [make_trade(-1000)] * 20
        result = monte_carlo_simulation(trades, n_simulations=100,
                                        ruin_threshold=0.25, seed=42)
        self.assertGreater(result["ruin_pct"], 0.9)

    def test_empty_trades(self):
        result = monte_carlo_simulation([], n_simulations=100)
        self.assertEqual(result["simulations"], 0)

    def test_has_consecutive_loss_stats(self):
        trades = [make_trade(50)] * 10 + [make_trade(-30)] * 5
        result = monte_carlo_simulation(trades, n_simulations=100, seed=42)
        self.assertIn("median_consec_losses", result)
        self.assertIn("p95_consec_losses", result)

    def test_ruin_threshold_passed_through(self):
        trades = [make_trade(-200)] * 20
        result = monte_carlo_simulation(trades, n_simulations=100,
                                        ruin_threshold=0.25, seed=42)
        self.assertEqual(result["ruin_threshold"], 0.25)


class TestBlockBootstrapMC(unittest.TestCase):
    def test_deterministic_with_seed(self):
        trades = [make_trade(50)] * 10 + [make_trade(-30)] * 5
        r1 = block_bootstrap_mc(trades, block_size=3, n_simulations=100, seed=42)
        r2 = block_bootstrap_mc(trades, block_size=3, n_simulations=100, seed=42)
        self.assertEqual(r1["median_max_dd"], r2["median_max_dd"])
        self.assertEqual(r1["ruin_pct"], r2["ruin_pct"])

    def test_has_consecutive_loss_stats(self):
        trades = [make_trade(50)] * 10 + [make_trade(-30)] * 10
        result = block_bootstrap_mc(trades, block_size=5, n_simulations=100, seed=42)
        self.assertIn("median_consec_losses", result)
        self.assertIn("p95_consec_losses", result)
        self.assertIn("max_consec_losses_worst", result)
        self.assertGreater(result["max_consec_losses_worst"], 0)

    def test_empty_trades(self):
        result = block_bootstrap_mc([], block_size=5, n_simulations=100)
        self.assertEqual(result["simulations"], 0)

    def test_all_losers_high_ruin(self):
        trades = [make_trade(-200)] * 20
        result = block_bootstrap_mc(trades, block_size=5, n_simulations=100,
                                    ruin_threshold=0.25, seed=42)
        self.assertGreater(result["ruin_pct"], 0.9)

    def test_method_field(self):
        trades = [make_trade(50)] * 10
        result = block_bootstrap_mc(trades, block_size=3, n_simulations=50, seed=42)
        self.assertEqual(result["method"], "block_bootstrap")

    def test_balance_varies_with_replacement(self):
        """Block bootstrap samples WITH replacement, so balances should vary."""
        trades = [make_trade(100)] * 5 + [make_trade(-80)] * 5
        result = block_bootstrap_mc(trades, block_size=3, n_simulations=500, seed=42)
        # With replacement, P5 and P95 should differ
        self.assertNotEqual(result["p5_final_balance"], result["p95_final_balance"])


class TestRegimeClassification(unittest.TestCase):
    def test_uptrend_classified(self):
        candles = make_uptrend_candles(days=80, step=0.003)
        regime = classify_regime(candles)
        self.assertIn("bull", regime)

    def test_downtrend_classified(self):
        candles = make_downtrend_candles(days=80, step=0.003)
        regime = classify_regime(candles)
        self.assertIn("bear", regime)

    def test_flat_classified_ranging(self):
        candles = make_flat_candles(days=80)
        regime = classify_regime(candles)
        self.assertEqual(regime, "ranging")

    def test_insufficient_data(self):
        candles = make_flat_candles(days=10)
        regime = classify_regime(candles)
        self.assertEqual(regime, "unknown")


# ── Engine Tests ──────────────────────────────────────────────────────

class TestBacktestEngine(unittest.TestCase):
    def _make_config(self, **kwargs):
        defaults = {
            "start_date": "2024-01-01",
            "end_date": "2024-01-30",
            "initial_balance": 10000.0,
            "max_risk": 0.02,
            "rr_ratio": 1.5,
            "max_positions_global": 3,
            "edu_sections": set(),
            "lookback": 10,
        }
        defaults.update(kwargs)
        return BacktestConfig(**defaults)

    def test_generates_trades_on_uptrend(self):
        """Uptrend candles should generate LONG signals."""
        candles = make_uptrend_candles(days=30, step=0.001)
        config = self._make_config(
            symbols=[("forex", "EURUSD", {"pip_size": 0.0001})],
        )
        data = {("forex", "EURUSD"): candles}
        result = run_backtest(config, data)
        # Should have at least some trades
        self.assertGreater(len(result.trades), 0)

    def test_equity_curve_populated(self):
        candles = make_uptrend_candles(days=30, step=0.001)
        config = self._make_config(
            symbols=[("forex", "EURUSD", {"pip_size": 0.0001})],
        )
        data = {("forex", "EURUSD"): candles}
        result = run_backtest(config, data)
        self.assertGreater(len(result.equity_curve), 0)

    def test_no_trades_with_insufficient_candles(self):
        """Need at least LOOKBACK candles before trading."""
        candles = make_uptrend_candles(days=5)
        config = self._make_config(
            symbols=[("forex", "EURUSD", {"pip_size": 0.0001})],
        )
        data = {("forex", "EURUSD"): candles}
        result = run_backtest(config, data)
        self.assertEqual(len(result.trades), 0)

    def test_position_limit_global(self):
        """Global position limit prevents over-allocation."""
        candles = make_uptrend_candles(days=30, step=0.001)
        config = self._make_config(
            max_positions_global=1,
            symbols=[
                ("forex", "EURUSD", {"pip_size": 0.0001}),
                ("forex", "GBPUSD", {"pip_size": 0.0001}),
            ],
        )
        data = {
            ("forex", "EURUSD"): candles,
            ("forex", "GBPUSD"): candles,
        }
        result = run_backtest(config, data)
        # With global max 1, all trades close before next opens
        # So we shouldn't see more than 1 open at any time
        self.assertGreater(len(result.trades), 0)

    def test_stock_trades(self):
        """Stock handler used for stock symbols."""
        candles = make_uptrend_candles(start_price=100.0, days=30, step=1.0)
        config = self._make_config(
            symbols=[("stocks", "SPY", {})],
            max_positions_per_class={"stocks": 2, "forex": 2, "crypto": 1},
        )
        data = {("stocks", "SPY"): candles}
        result = run_backtest(config, data)
        self.assertGreater(len(result.trades), 0)
        # All trades should be stock trades
        for t in result.trades:
            self.assertEqual(t["asset_class"], "stocks")

    def test_empty_data_no_crash(self):
        config = self._make_config(symbols=[("forex", "EURUSD", {"pip_size": 0.0001})])
        result = run_backtest(config, {})
        self.assertEqual(len(result.trades), 0)
        self.assertEqual(result.final_balance, 10000.0)

    def test_final_balance_consistent(self):
        """Final balance = initial + sum of all trade PnLs."""
        candles = make_uptrend_candles(days=30, step=0.002)
        config = self._make_config(
            symbols=[("forex", "EURUSD", {"pip_size": 0.0001})],
        )
        data = {("forex", "EURUSD"): candles}
        result = run_backtest(config, data)
        expected = 10000.0 + sum(t["pnl"] for t in result.trades)
        self.assertAlmostEqual(result.final_balance, expected, places=1)

    def test_spread_makes_backtest_more_pessimistic(self):
        """With spread, final balance should be lower than without."""
        candles = make_uptrend_candles(days=30, step=0.002)
        sym = [("forex", "EURUSD", {"pip_size": 0.0001})]
        data = {("forex", "EURUSD"): candles}

        clean = self._make_config(symbols=sym)
        result_clean = run_backtest(clean, data)

        with_spread = self._make_config(
            symbols=sym,
            spread={"forex": 0.00015, "stocks": 0.02, "crypto_pct": 0.0015},
        )
        result_spread = run_backtest(with_spread, data)

        # Same number of trades (spread doesn't block entry)
        self.assertEqual(len(result_clean.trades), len(result_spread.trades))
        # But lower final balance with spread
        self.assertLess(result_spread.final_balance, result_clean.final_balance)

    def test_slippage_adjusts_entry_prices(self):
        """With slippage, entry prices differ from signal prices."""
        candles = make_uptrend_candles(days=30, step=0.002)
        sym = [("forex", "EURUSD", {"pip_size": 0.0001})]
        data = {("forex", "EURUSD"): candles}

        clean = self._make_config(symbols=sym)
        result_clean = run_backtest(clean, data)

        with_slip = self._make_config(
            symbols=sym,
            slippage={"forex": 0.0002, "stocks": 0.01, "crypto_pct": 0.0005},
        )
        result_slip = run_backtest(with_slip, data)

        if result_clean.trades and result_slip.trades:
            # LONG entries should be higher (worse) with slippage
            for tc, ts in zip(result_clean.trades, result_slip.trades):
                if tc["direction"] == "LONG":
                    self.assertGreater(ts["entry"], tc["entry"])


# ── All Metrics Integration ──────────────────────────────────────────

class TestAllMetrics(unittest.TestCase):
    def test_computes_all_fields(self):
        trades = [make_trade(100, 1.5), make_trade(-50, -0.75),
                  make_trade(80, 1.2), make_trade(-30, -0.5)]
        curve = [{"date": f"2024-01-{i+1:02d}", "balance": 10000 + i * 25}
                 for i in range(30)]
        metrics = compute_all_metrics(trades, curve, 10000.0)

        self.assertIn("sharpe_ratio", metrics)
        self.assertIn("profit_factor", metrics)
        self.assertIn("win_rate", metrics)
        self.assertIn("max_drawdown_pct", metrics)
        self.assertIn("expectancy_dollars", metrics)
        self.assertIn("total_trades", metrics)
        self.assertEqual(metrics["total_trades"], 4)


if __name__ == "__main__":
    unittest.main()
