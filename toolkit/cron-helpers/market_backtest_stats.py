#!/usr/bin/env python3
"""Statistical analysis for backtest validation.

Pure Python (stdlib only). Computes expectancy, Sharpe, Sortino, profit
factor, max drawdown, Monte Carlo, walk-forward analysis, parameter
stability, and regime classification.
"""

import math
import random
import statistics
from datetime import datetime


# ── Core Metrics ──────────────────────────────────────────────────────

def compute_expectancy(trades):
    """Average expected P&L per trade in R-multiples.

    E = (win% × avg_win_R) − (loss% × avg_loss_R)
    """
    if not trades:
        return 0.0
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    n = len(trades)
    win_rate = len(wins) / n
    loss_rate = len(losses) / n
    avg_win = statistics.mean([t["rr_achieved"] for t in wins]) if wins else 0
    avg_loss = statistics.mean([abs(t["rr_achieved"]) for t in losses]) if losses else 0
    return win_rate * avg_win - loss_rate * avg_loss


def compute_expectancy_dollars(trades):
    """Average expected P&L per trade in dollars."""
    if not trades:
        return 0.0
    return statistics.mean([t["pnl"] for t in trades])


def compute_profit_factor(trades):
    """sum(wins) / abs(sum(losses)). Returns inf if no losses."""
    gross_win = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] <= 0))
    if gross_loss == 0:
        return float("inf") if gross_win > 0 else 0.0
    return gross_win / gross_loss


def compute_win_rate(trades):
    """Fraction of trades with positive P&L."""
    if not trades:
        return 0.0
    return sum(1 for t in trades if t["pnl"] > 0) / len(trades)


def compute_avg_rr(trades):
    """Average R-multiple achieved across all trades."""
    rrs = [t["rr_achieved"] for t in trades if t.get("rr_achieved") is not None]
    return statistics.mean(rrs) if rrs else 0.0


def compute_consecutive_stats(trades):
    """Max consecutive wins and losses."""
    max_wins = max_losses = cur_wins = cur_losses = 0
    for t in trades:
        if t["pnl"] > 0:
            cur_wins += 1
            cur_losses = 0
        else:
            cur_losses += 1
            cur_wins = 0
        max_wins = max(max_wins, cur_wins)
        max_losses = max(max_losses, cur_losses)
    return {"max_consecutive_wins": max_wins, "max_consecutive_losses": max_losses}


# ── Equity Curve Metrics ──────────────────────────────────────────────

def compute_daily_returns(equity_curve):
    """Extract daily returns from equity curve [{date, balance}, ...]."""
    if len(equity_curve) < 2:
        return []
    returns = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]["balance"]
        curr = equity_curve[i]["balance"]
        if prev > 0:
            returns.append((curr - prev) / prev)
        else:
            returns.append(0.0)
    return returns


def compute_sharpe_ratio(equity_curve, risk_free_rate=0.0):
    """Annualized Sharpe from daily equity curve.

    sharpe = (mean_daily - rf_daily) / stdev_daily × sqrt(252)
    """
    returns = compute_daily_returns(equity_curve)
    if len(returns) < 2:
        return 0.0
    rf_daily = risk_free_rate / 252
    excess = [r - rf_daily for r in returns]
    try:
        sd = statistics.stdev(excess)
    except statistics.StatisticsError:
        return 0.0
    if sd == 0:
        return 0.0
    return (statistics.mean(excess) / sd) * math.sqrt(252)


def compute_sortino_ratio(equity_curve, risk_free_rate=0.0):
    """Like Sharpe but only penalizes downside deviation."""
    returns = compute_daily_returns(equity_curve)
    if len(returns) < 2:
        return 0.0
    rf_daily = risk_free_rate / 252
    excess = [r - rf_daily for r in returns]
    downside = [r for r in excess if r < 0]
    if not downside:
        return float("inf") if statistics.mean(excess) > 0 else 0.0
    down_dev = math.sqrt(statistics.mean([r ** 2 for r in downside]))
    if down_dev == 0:
        return 0.0
    return (statistics.mean(excess) / down_dev) * math.sqrt(252)


def compute_max_drawdown(equity_curve):
    """Peak-to-trough drawdown.

    Returns (max_dd_pct, max_dd_dollar, peak_date, trough_date).
    """
    if not equity_curve:
        return 0.0, 0.0, "", ""

    peak = equity_curve[0]["balance"]
    peak_date = equity_curve[0]["date"]
    max_dd_pct = 0.0
    max_dd_dollar = 0.0
    trough_date = peak_date
    dd_peak_date = peak_date

    for point in equity_curve:
        bal = point["balance"]
        if bal >= peak:
            peak = bal
            peak_date = point["date"]
        dd = (peak - bal) / peak if peak > 0 else 0
        dd_dollar = peak - bal
        if dd > max_dd_pct:
            max_dd_pct = dd
            max_dd_dollar = dd_dollar
            trough_date = point["date"]
            dd_peak_date = peak_date

    return max_dd_pct, max_dd_dollar, dd_peak_date, trough_date


def compute_calmar_ratio(equity_curve, initial_balance):
    """CAGR / max drawdown. Higher = better risk-adjusted return."""
    if not equity_curve or len(equity_curve) < 2:
        return 0.0
    final = equity_curve[-1]["balance"]
    start_date = equity_curve[0]["date"]
    end_date = equity_curve[-1]["date"]
    days = (datetime.fromisoformat(end_date) - datetime.fromisoformat(start_date)).days
    if days <= 0:
        return 0.0
    years = days / 365.25
    if initial_balance <= 0 or final <= 0:
        return 0.0
    cagr = (final / initial_balance) ** (1.0 / years) - 1
    dd_pct = compute_max_drawdown(equity_curve)[0]
    if dd_pct == 0:
        return float("inf") if cagr > 0 else 0.0
    return cagr / dd_pct


def compute_cagr(equity_curve, initial_balance):
    """Compound annual growth rate."""
    if not equity_curve or len(equity_curve) < 2:
        return 0.0
    final = equity_curve[-1]["balance"]
    start_date = equity_curve[0]["date"]
    end_date = equity_curve[-1]["date"]
    days = (datetime.fromisoformat(end_date) - datetime.fromisoformat(start_date)).days
    if days <= 0 or initial_balance <= 0 or final <= 0:
        return 0.0
    years = days / 365.25
    return (final / initial_balance) ** (1.0 / years) - 1


# ── Monte Carlo Simulation ───────────────────────────────────────────

def monte_carlo_simulation(trades, n_simulations=5000, initial_balance=10000.0,
                           ruin_threshold=0.50, seed=None):
    """Shuffle trade P&L order, re-simulate equity curve each time.

    Returns distribution of outcomes to test robustness against lucky
    sequencing.
    """
    if not trades:
        return {
            "simulations": 0, "profitable_pct": 0.0,
            "median_final_balance": initial_balance,
            "p5_final_balance": initial_balance,
            "p95_final_balance": initial_balance,
            "median_max_drawdown": 0.0, "p95_max_drawdown": 0.0,
            "ruin_pct": 0.0,
        }

    pnls = [t["pnl"] for t in trades]
    rng = random.Random(seed)

    final_balances = []
    max_drawdowns = []
    ruin_count = 0

    for _ in range(n_simulations):
        shuffled = pnls[:]
        rng.shuffle(shuffled)

        balance = initial_balance
        peak = initial_balance
        max_dd = 0.0

        for pnl in shuffled:
            balance += pnl
            if balance > peak:
                peak = balance
            dd = (peak - balance) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        final_balances.append(balance)
        max_drawdowns.append(max_dd)
        if max_dd >= ruin_threshold:
            ruin_count += 1

    final_balances.sort()
    max_drawdowns.sort()
    n = len(final_balances)

    return {
        "simulations": n_simulations,
        "profitable_pct": sum(1 for b in final_balances if b > initial_balance) / n,
        "median_final_balance": round(final_balances[n // 2], 2),
        "p5_final_balance": round(final_balances[int(n * 0.05)], 2),
        "p95_final_balance": round(final_balances[int(n * 0.95)], 2),
        "mean_final_balance": round(statistics.mean(final_balances), 2),
        "median_max_drawdown": round(max_drawdowns[n // 2], 4),
        "p95_max_drawdown": round(max_drawdowns[int(n * 0.95)], 4),
        "ruin_pct": round(ruin_count / n, 4),
    }


# ── Regime Analysis ──────────────────────────────────────────────────

def compute_atr(candles, period=20):
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


def classify_regime(candles, lookback=60):
    """Classify market regime from candle data.

    Returns one of: bull_low_vol, bull_high_vol, bear_low_vol,
    bear_high_vol, ranging.
    """
    if len(candles) < max(lookback, 21):
        return "unknown"

    # Trend: SMA(20) slope
    recent = candles[-lookback:]
    sma_start = statistics.mean([c["c"] for c in recent[:20]])
    sma_end = statistics.mean([c["c"] for c in recent[-20:]])
    sma_change = (sma_end - sma_start) / sma_start if sma_start > 0 else 0

    # Volatility: ATR(20) / SMA(20)
    atr = compute_atr(candles, 20)
    sma = statistics.mean([c["c"] for c in candles[-20:]])
    vol_ratio = atr / sma if sma > 0 and atr else 0

    # Compute historical median vol ratio for relative comparison
    # Use a simple threshold: >1% daily range = high vol for most assets
    high_vol = vol_ratio > 0.015

    if abs(sma_change) < 0.02:  # <2% move over lookback = ranging
        return "ranging"
    elif sma_change > 0:
        return "bull_high_vol" if high_vol else "bull_low_vol"
    else:
        return "bear_high_vol" if high_vol else "bear_low_vol"


def segment_by_regime(trades, candle_data):
    """Group trades by market regime at entry date.

    candle_data: {(asset_class, symbol): [sorted candles]}
    Returns {regime: [trades_in_regime]}.
    """
    regimes = {}
    for t in trades:
        key = (t["asset_class"], t["symbol"])
        candles = candle_data.get(key, [])
        # Find candle index for entry date
        entry_idx = None
        for i, c in enumerate(candles):
            if c["date"] == t["entry_date"]:
                entry_idx = i
                break
        if entry_idx is None or entry_idx < 60:
            regime = "unknown"
        else:
            regime = classify_regime(candles[:entry_idx + 1])

        regimes.setdefault(regime, []).append(t)
    return regimes


def compute_regime_metrics(regime_trades):
    """Compute core metrics per regime bucket."""
    results = {}
    for regime, trades in regime_trades.items():
        results[regime] = {
            "count": len(trades),
            "win_rate": compute_win_rate(trades),
            "expectancy": compute_expectancy_dollars(trades),
            "profit_factor": compute_profit_factor(trades),
            "avg_rr": compute_avg_rr(trades),
        }
    return results


# ── All Metrics Bundle ────────────────────────────────────────────────

def compute_all_metrics(trades, equity_curve, initial_balance):
    """Compute all core metrics in one call."""
    consec = compute_consecutive_stats(trades)
    dd_pct, dd_dollar, dd_peak, dd_trough = compute_max_drawdown(equity_curve)

    return {
        "total_trades": len(trades),
        "win_rate": round(compute_win_rate(trades), 4),
        "expectancy_r": round(compute_expectancy(trades), 4),
        "expectancy_dollars": round(compute_expectancy_dollars(trades), 2),
        "profit_factor": round(compute_profit_factor(trades), 4),
        "sharpe_ratio": round(compute_sharpe_ratio(equity_curve), 4),
        "sortino_ratio": round(compute_sortino_ratio(equity_curve), 4),
        "calmar_ratio": round(compute_calmar_ratio(equity_curve, initial_balance), 4),
        "cagr": round(compute_cagr(equity_curve, initial_balance), 4),
        "max_drawdown_pct": round(dd_pct, 4),
        "max_drawdown_dollar": round(dd_dollar, 2),
        "drawdown_peak_date": dd_peak,
        "drawdown_trough_date": dd_trough,
        "avg_rr_achieved": round(compute_avg_rr(trades), 4),
        "max_consecutive_wins": consec["max_consecutive_wins"],
        "max_consecutive_losses": consec["max_consecutive_losses"],
        "avg_win": round(statistics.mean([t["pnl"] for t in trades if t["pnl"] > 0]), 2) if any(t["pnl"] > 0 for t in trades) else 0.0,
        "avg_loss": round(statistics.mean([t["pnl"] for t in trades if t["pnl"] <= 0]), 2) if any(t["pnl"] <= 0 for t in trades) else 0.0,
        "initial_balance": initial_balance,
        "final_balance": round(equity_curve[-1]["balance"], 2) if equity_curve else initial_balance,
    }
