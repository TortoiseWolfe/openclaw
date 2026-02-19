#!/usr/bin/env python3
"""Backtest runner — orchestrates validation and writes reports.

Usage (from Docker):
  python3 market_backtest_run.py                  # Full validation suite
  python3 market_backtest_run.py --quick           # Single backtest, basic stats
  python3 market_backtest_run.py --monte-carlo     # MC simulation only (needs prior backtest)
  python3 market_backtest_run.py --walk-forward    # Walk-forward only
  python3 market_backtest_run.py --param-scan      # Parameter scan only
  python3 market_backtest_run.py --symbol EURUSD   # Single symbol
  python3 market_backtest_run.py --edu all         # All education unlocked
  python3 market_backtest_run.py --edu none        # Baseline (no education)
  python3 market_backtest_run.py --start 2020-01-01 --end 2025-12-31
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from market_backtest_engine import (
    BacktestConfig,
    load_historical_candles,
    load_watchlist_symbols,
    run_backtest,
)
from market_backtest_stats import (
    compute_all_metrics,
    compute_regime_metrics,
    monte_carlo_simulation,
    segment_by_regime,
)

# ── Paths ─────────────────────────────────────────────────────────────

VALIDATION_DIR = "/home/node/repos/Trading/private/validation"

# ── Pass/Fail Thresholds ─────────────────────────────────────────────

THRESHOLDS = {
    "min_trades": 200,
    "min_sharpe": 1.0,
    "min_profit_factor": 1.3,
    "max_drawdown_pct": 0.30,
    "min_win_rate": 0.35,
    "min_expectancy_dollars": 0.0,
    "mc_profitable_pct": 0.80,
    "mc_ruin_pct_max": 0.05,
}

# All possible education sections
ALL_EDU_SECTIONS = {
    "Japanese Candlesticks", "Fibonacci", "Moving Averages",
    "Support and Resistance Levels", "Popular Chart Indicators",
    "Oscillators and Momentum Indicators", "Important Chart Patterns",
    "Pivot Points", "Trading Divergences", "Risk Management",
    "Position Sizing",
}


# ── CLI Argument Parsing ──────────────────────────────────────────────

def parse_args():
    args = {
        "quick": False,
        "monte_carlo_only": False,
        "walk_forward_only": False,
        "param_scan_only": False,
        "symbol": None,
        "edu": None,  # None=current, "all", "none"
        "start": "2015-01-01",
        "end": "2025-12-31",
    }
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        if argv[i] == "--quick":
            args["quick"] = True
        elif argv[i] == "--monte-carlo":
            args["monte_carlo_only"] = True
        elif argv[i] == "--walk-forward":
            args["walk_forward_only"] = True
        elif argv[i] == "--param-scan":
            args["param_scan_only"] = True
        elif argv[i] == "--symbol" and i + 1 < len(argv):
            args["symbol"] = argv[i + 1]
            i += 1
        elif argv[i] == "--edu" and i + 1 < len(argv):
            args["edu"] = argv[i + 1]
            i += 1
        elif argv[i] == "--start" and i + 1 < len(argv):
            args["start"] = argv[i + 1]
            i += 1
        elif argv[i] == "--end" and i + 1 < len(argv):
            args["end"] = argv[i + 1]
            i += 1
        i += 1
    return args


def resolve_edu_sections(edu_arg):
    """Resolve education argument to a set of sections."""
    if edu_arg == "all":
        return ALL_EDU_SECTIONS.copy()
    if edu_arg == "none":
        return set()
    # Default: load current progress
    try:
        from trading_signals import load_education_progress
        sections, _, _ = load_education_progress()
        return sections
    except Exception:
        return set()


# ── Walk-Forward Analysis ─────────────────────────────────────────────

def walk_forward_analysis(candle_data, symbols, rules, edu_sections,
                          train_days=504, test_days=126):
    """Rolling window: optimize on train, validate on test.

    train_days: ~2 years of trading days
    test_days: ~6 months of trading days
    """
    # Get all dates from the data
    all_dates = set()
    for candles in candle_data.values():
        for c in candles:
            all_dates.add(c["date"])
    all_dates = sorted(all_dates)

    if len(all_dates) < train_days + test_days:
        return {"windows": [], "error": "Insufficient data for walk-forward"}

    # Parameter grid for optimization (small for speed)
    rr_values = [1.0, 1.5, 2.0, 2.5]
    lookback_values = [8, 10, 15]

    windows = []
    offset = 0

    while offset + train_days + test_days <= len(all_dates):
        train_start = all_dates[offset]
        train_end = all_dates[offset + train_days - 1]
        test_start = all_dates[offset + train_days]
        test_end_idx = min(offset + train_days + test_days - 1, len(all_dates) - 1)
        test_end = all_dates[test_end_idx]

        # Train: find best params
        best_sharpe = -999
        best_params = {"rr_ratio": 1.5, "lookback": 10}

        for rr in rr_values:
            for lb in lookback_values:
                cfg = BacktestConfig(
                    start_date=train_start, end_date=train_end,
                    max_risk=0.02, rr_ratio=rr, lookback=lb,
                    edu_sections=edu_sections, symbols=symbols,
                )
                res = run_backtest(cfg, candle_data)
                if not res.trades:
                    continue
                metrics = compute_all_metrics(
                    res.trades, res.equity_curve, cfg.initial_balance)
                if metrics["sharpe_ratio"] > best_sharpe:
                    best_sharpe = metrics["sharpe_ratio"]
                    best_params = {"rr_ratio": rr, "lookback": lb}

        # Test: run with best params from train
        cfg = BacktestConfig(
            start_date=test_start, end_date=test_end,
            max_risk=0.02, rr_ratio=best_params["rr_ratio"],
            lookback=best_params["lookback"],
            edu_sections=edu_sections, symbols=symbols,
        )
        res = run_backtest(cfg, candle_data)
        test_metrics = compute_all_metrics(
            res.trades, res.equity_curve, cfg.initial_balance) if res.trades else {}

        windows.append({
            "train_period": f"{train_start} to {train_end}",
            "test_period": f"{test_start} to {test_end}",
            "best_params": best_params,
            "train_sharpe": round(best_sharpe, 4),
            "test_trades": len(res.trades),
            "test_sharpe": test_metrics.get("sharpe_ratio", 0),
            "test_pf": test_metrics.get("profit_factor", 0),
            "test_win_rate": test_metrics.get("win_rate", 0),
            "test_final_balance": res.final_balance,
        })

        offset += test_days  # Roll forward by test window size

    profitable_windows = sum(1 for w in windows if w["test_final_balance"] > 10000)
    consistency = profitable_windows / len(windows) if windows else 0

    return {
        "windows": windows,
        "total_windows": len(windows),
        "profitable_windows": profitable_windows,
        "consistency_pct": round(consistency, 4),
    }


# ── Parameter Stability Scan ─────────────────────────────────────────

def parameter_scan(candle_data, symbols, edu_sections, start, end):
    """Grid search over parameter combinations."""
    rr_values = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]
    risk_values = [0.01, 0.015, 0.02, 0.025, 0.03]
    lookback_values = [5, 8, 10, 15, 20]

    results = []
    total = len(rr_values) * len(risk_values) * len(lookback_values)
    done = 0

    for rr in rr_values:
        for risk in risk_values:
            for lb in lookback_values:
                cfg = BacktestConfig(
                    start_date=start, end_date=end,
                    max_risk=risk, rr_ratio=rr, lookback=lb,
                    edu_sections=edu_sections, symbols=symbols,
                )
                res = run_backtest(cfg, candle_data)
                if res.trades:
                    metrics = compute_all_metrics(
                        res.trades, res.equity_curve, cfg.initial_balance)
                else:
                    metrics = {"sharpe_ratio": 0, "profit_factor": 0,
                              "win_rate": 0, "total_trades": 0,
                              "max_drawdown_pct": 0, "expectancy_dollars": 0}

                results.append({
                    "rr_ratio": rr,
                    "max_risk": risk,
                    "lookback": lb,
                    "trades": metrics.get("total_trades", 0),
                    "sharpe": metrics.get("sharpe_ratio", 0),
                    "profit_factor": metrics.get("profit_factor", 0),
                    "win_rate": metrics.get("win_rate", 0),
                    "max_drawdown": metrics.get("max_drawdown_pct", 0),
                    "expectancy": metrics.get("expectancy_dollars", 0),
                    "final_balance": res.final_balance,
                })
                done += 1
                if done % 25 == 0:
                    print(f"  Parameter scan: {done}/{total} combinations...")

    # Find stable plateau: params where neighbors are also positive Sharpe
    positive = {(r["rr_ratio"], r["max_risk"], r["lookback"])
                for r in results if r["sharpe"] > 0}

    stable = []
    for r in results:
        if r["sharpe"] <= 0:
            continue
        key = (r["rr_ratio"], r["max_risk"], r["lookback"])
        # Check if neighbors are also positive
        ri, mi, li = rr_values.index(r["rr_ratio"]), risk_values.index(r["max_risk"]), lookback_values.index(r["lookback"])
        neighbor_count = 0
        total_neighbors = 0
        for di in [-1, 1]:
            if 0 <= ri + di < len(rr_values):
                total_neighbors += 1
                if (rr_values[ri + di], r["max_risk"], r["lookback"]) in positive:
                    neighbor_count += 1
            if 0 <= mi + di < len(risk_values):
                total_neighbors += 1
                if (r["rr_ratio"], risk_values[mi + di], r["lookback"]) in positive:
                    neighbor_count += 1
            if 0 <= li + di < len(lookback_values):
                total_neighbors += 1
                if (r["rr_ratio"], r["max_risk"], lookback_values[li + di]) in positive:
                    neighbor_count += 1
        stability = neighbor_count / total_neighbors if total_neighbors > 0 else 0
        if stability >= 0.5:
            stable.append({**r, "stability_score": round(stability, 2)})

    best = max(stable, key=lambda x: x["sharpe"]) if stable else (
        max(results, key=lambda x: x["sharpe"]) if results else None)

    return {
        "total_combinations": total,
        "positive_sharpe_count": len(positive),
        "stable_count": len(stable),
        "best_stable": best,
        "grid": results,
    }


# ── Report Generation ─────────────────────────────────────────────────

def write_json_report(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def write_markdown_report(metrics, mc_results, wf_results, param_results,
                          regime_results, config_info):
    """Write human-readable validation report."""
    lines = []
    lines.append(f"# Backtest Validation Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append(f"**Data range:** {config_info['start']} to {config_info['end']}")
    lines.append(f"**Education:** {config_info['edu_label']}")
    lines.append(f"**Symbols tested:** {config_info['symbol_count']}")
    lines.append("")

    # ── Summary Pass/Fail ──
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value | Threshold | Result |")
    lines.append("|--------|-------|-----------|--------|")

    checks = [
        ("Total trades", metrics.get("total_trades", 0), f">= {THRESHOLDS['min_trades']}", metrics.get("total_trades", 0) >= THRESHOLDS["min_trades"]),
        ("Sharpe ratio", f"{metrics.get('sharpe_ratio', 0):.4f}", f">= {THRESHOLDS['min_sharpe']}", metrics.get("sharpe_ratio", 0) >= THRESHOLDS["min_sharpe"]),
        ("Profit factor", f"{metrics.get('profit_factor', 0):.4f}", f">= {THRESHOLDS['min_profit_factor']}", metrics.get("profit_factor", 0) >= THRESHOLDS["min_profit_factor"]),
        ("Max drawdown", f"{metrics.get('max_drawdown_pct', 0):.1%}", f"<= {THRESHOLDS['max_drawdown_pct']:.0%}", metrics.get("max_drawdown_pct", 0) <= THRESHOLDS["max_drawdown_pct"]),
        ("Win rate", f"{metrics.get('win_rate', 0):.1%}", f">= {THRESHOLDS['min_win_rate']:.0%}", metrics.get("win_rate", 0) >= THRESHOLDS["min_win_rate"]),
        ("Expectancy ($/trade)", f"${metrics.get('expectancy_dollars', 0):.2f}", "> $0", metrics.get("expectancy_dollars", 0) > THRESHOLDS["min_expectancy_dollars"]),
    ]

    if mc_results:
        checks.append(("MC profitable %", f"{mc_results.get('profitable_pct', 0):.1%}", f">= {THRESHOLDS['mc_profitable_pct']:.0%}", mc_results.get("profitable_pct", 0) >= THRESHOLDS["mc_profitable_pct"]))
        checks.append(("MC ruin %", f"{mc_results.get('ruin_pct', 0):.1%}", f"<= {THRESHOLDS['mc_ruin_pct_max']:.0%}", mc_results.get("ruin_pct", 0) <= THRESHOLDS["mc_ruin_pct_max"]))

    all_pass = True
    for name, value, threshold, passed in checks:
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        lines.append(f"| {name} | {value} | {threshold} | {status} |")

    lines.append("")

    # ── Trade Statistics ──
    lines.append("## Trade Statistics")
    lines.append("")
    lines.append(f"- **Total trades:** {metrics.get('total_trades', 0)}")
    lines.append(f"- **Win rate:** {metrics.get('win_rate', 0):.1%}")
    lines.append(f"- **Avg win:** ${metrics.get('avg_win', 0):.2f}")
    lines.append(f"- **Avg loss:** ${metrics.get('avg_loss', 0):.2f}")
    lines.append(f"- **Expectancy (R):** {metrics.get('expectancy_r', 0):.4f}")
    lines.append(f"- **Expectancy ($):** ${metrics.get('expectancy_dollars', 0):.2f}")
    lines.append(f"- **Profit factor:** {metrics.get('profit_factor', 0):.4f}")
    lines.append(f"- **Avg R:R achieved:** {metrics.get('avg_rr_achieved', 0):.4f}")
    lines.append(f"- **Max consecutive wins:** {metrics.get('max_consecutive_wins', 0)}")
    lines.append(f"- **Max consecutive losses:** {metrics.get('max_consecutive_losses', 0)}")
    lines.append("")

    # ── Risk Metrics ──
    lines.append("## Risk Metrics")
    lines.append("")
    lines.append(f"- **Sharpe ratio:** {metrics.get('sharpe_ratio', 0):.4f}")
    lines.append(f"- **Sortino ratio:** {metrics.get('sortino_ratio', 0):.4f}")
    lines.append(f"- **Calmar ratio:** {metrics.get('calmar_ratio', 0):.4f}")
    lines.append(f"- **CAGR:** {metrics.get('cagr', 0):.2%}")
    lines.append(f"- **Max drawdown:** {metrics.get('max_drawdown_pct', 0):.2%} (${metrics.get('max_drawdown_dollar', 0):.2f})")
    lines.append(f"- **Drawdown period:** {metrics.get('drawdown_peak_date', '?')} to {metrics.get('drawdown_trough_date', '?')}")
    lines.append(f"- **Initial balance:** ${metrics.get('initial_balance', 10000):.2f}")
    lines.append(f"- **Final balance:** ${metrics.get('final_balance', 0):.2f}")
    lines.append("")

    # ── Monte Carlo ──
    if mc_results:
        lines.append("## Monte Carlo Analysis")
        lines.append("")
        lines.append(f"- **Simulations:** {mc_results.get('simulations', 0)}")
        lines.append(f"- **Profitable runs:** {mc_results.get('profitable_pct', 0):.1%}")
        lines.append(f"- **Ruin probability (50% DD):** {mc_results.get('ruin_pct', 0):.1%}")
        lines.append(f"- **Median final balance:** ${mc_results.get('median_final_balance', 0):.2f}")
        lines.append(f"- **P5 (worst 5%):** ${mc_results.get('p5_final_balance', 0):.2f}")
        lines.append(f"- **P95 (best 5%):** ${mc_results.get('p95_final_balance', 0):.2f}")
        lines.append(f"- **Median max drawdown:** {mc_results.get('median_max_drawdown', 0):.2%}")
        lines.append(f"- **P95 max drawdown:** {mc_results.get('p95_max_drawdown', 0):.2%}")
        lines.append("")

    # ── Walk-Forward ──
    if wf_results and wf_results.get("windows"):
        lines.append("## Walk-Forward Analysis")
        lines.append("")
        lines.append(f"- **Windows:** {wf_results['total_windows']}")
        lines.append(f"- **Profitable OOS:** {wf_results['profitable_windows']}/{wf_results['total_windows']} ({wf_results['consistency_pct']:.0%})")
        lines.append("")
        lines.append("| Window | Train Sharpe | Test Sharpe | Test PF | Test WR | Balance |")
        lines.append("|--------|-------------|-------------|---------|---------|---------|")
        for w in wf_results["windows"]:
            lines.append(f"| {w['test_period']} | {w['train_sharpe']:.2f} | {w['test_sharpe']:.2f} | {w['test_pf']:.2f} | {w['test_win_rate']:.1%} | ${w['test_final_balance']:.0f} |")
        lines.append("")

    # ── Parameter Stability ──
    if param_results:
        lines.append("## Parameter Stability")
        lines.append("")
        lines.append(f"- **Combinations tested:** {param_results['total_combinations']}")
        lines.append(f"- **Positive Sharpe:** {param_results['positive_sharpe_count']}/{param_results['total_combinations']}")
        lines.append(f"- **Stable (plateau):** {param_results['stable_count']}")
        if param_results.get("best_stable"):
            b = param_results["best_stable"]
            lines.append(f"- **Best stable params:** RR={b['rr_ratio']}, Risk={b['max_risk']:.1%}, Lookback={b['lookback']}")
            lines.append(f"  - Sharpe={b['sharpe']:.2f}, PF={b['profit_factor']:.2f}, WR={b['win_rate']:.1%}, Stability={b.get('stability_score', 0):.0%}")
        lines.append("")

    # ── Regime Analysis ──
    if regime_results:
        lines.append("## Regime Analysis")
        lines.append("")
        lines.append("| Regime | Trades | Win Rate | Expectancy | PF |")
        lines.append("|--------|--------|----------|------------|-----|")
        positive_regimes = 0
        for regime, m in sorted(regime_results.items()):
            lines.append(f"| {regime} | {m['count']} | {m['win_rate']:.1%} | ${m['expectancy']:.2f} | {m['profit_factor']:.2f} |")
            if m["expectancy"] > 0:
                positive_regimes += 1
        lines.append("")
        lines.append(f"Positive expectancy in {positive_regimes}/{len(regime_results)} regimes")
        lines.append("")

    # ── Verdict ──
    lines.append("## Verdict")
    lines.append("")
    if all_pass:
        lines.append("**PASS** — Strategy shows statistically validated positive expectancy.")
        lines.append("Safe to continue paper trading with confidence. Review walk-forward")
        lines.append("consistency and regime breakdown before considering capital scaling.")
    else:
        failed = [name for name, _, _, passed in checks if not passed]
        lines.append(f"**FAIL** — Strategy does not meet validation thresholds.")
        lines.append(f"Failed checks: {', '.join(failed)}")
        lines.append("")
        lines.append("This is expected for early-stage signal logic. As more BabyPips")
        lines.append("sections unlock (candlesticks, SMA, indicators), re-run validation.")
        lines.append("The parameter scan shows which settings are most promising.")

    lines.append("")

    path = os.path.join(VALIDATION_DIR, "validation-report.md")
    os.makedirs(VALIDATION_DIR, exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


# ── Main Orchestration ────────────────────────────────────────────────

def main():
    args = parse_args()
    edu_sections = resolve_edu_sections(args.get("edu"))

    edu_label = args.get("edu", "current")
    if edu_label == "all":
        edu_label = f"all ({len(ALL_EDU_SECTIONS)} sections)"
    elif edu_label == "none":
        edu_label = "none (baseline)"
    else:
        edu_label = f"current ({len(edu_sections)} sections)"

    print(f"Loading watchlist and candle data...")
    symbols, rules = load_watchlist_symbols()

    # Filter to single symbol if requested
    if args["symbol"]:
        symbols = [(ac, sym, cfg) for ac, sym, cfg in symbols
                   if sym == args["symbol"]]
        if not symbols:
            print(f"ERROR: Symbol {args['symbol']} not in watchlist", file=sys.stderr)
            sys.exit(1)

    candle_data = load_historical_candles(symbols)

    # Report data ranges
    for key, candles in candle_data.items():
        if candles:
            print(f"  {key[0]:6s} {key[1]:6s}: {len(candles)} candles ({candles[0]['date']} to {candles[-1]['date']})")

    config_info = {
        "start": args["start"],
        "end": args["end"],
        "edu_label": edu_label,
        "symbol_count": len(symbols),
    }

    # ── Run main backtest ────────────────────────────────────────
    print(f"\nRunning backtest ({args['start']} to {args['end']})...")
    cfg = BacktestConfig(
        start_date=args["start"],
        end_date=args["end"],
        max_risk=rules.get("max_risk", 0.02),
        rr_ratio=rules.get("rr_ratio", 1.5),
        edu_sections=edu_sections,
        symbols=symbols,
    )
    result = run_backtest(cfg, candle_data)
    print(f"  {len(result.trades)} trades, final balance: ${result.final_balance:.2f}")

    if not result.trades:
        print("ERROR: No trades generated. Check data range and candle availability.")
        sys.exit(1)

    # Save raw trades
    write_json_report(
        os.path.join(VALIDATION_DIR, "backtest-results.json"),
        {"trades": result.trades, "equity_curve_length": len(result.equity_curve),
         "final_balance": result.final_balance})

    # ── Core metrics ─────────────────────────────────────────────
    metrics = compute_all_metrics(result.trades, result.equity_curve, cfg.initial_balance)
    print(f"\n  Sharpe: {metrics['sharpe_ratio']:.4f}")
    print(f"  Profit Factor: {metrics['profit_factor']:.4f}")
    print(f"  Win Rate: {metrics['win_rate']:.1%}")
    print(f"  Max DD: {metrics['max_drawdown_pct']:.2%}")
    print(f"  Expectancy: ${metrics['expectancy_dollars']:.2f}/trade")

    mc_results = None
    wf_results = None
    param_results = None
    regime_results = None

    if args["quick"]:
        print("\n  (--quick mode: skipping MC, walk-forward, param scan)")
    else:
        # ── Monte Carlo ──────────────────────────────────────────
        if not args["walk_forward_only"] and not args["param_scan_only"]:
            print(f"\nRunning Monte Carlo (5000 simulations)...")
            mc_results = monte_carlo_simulation(
                result.trades, n_simulations=5000,
                initial_balance=cfg.initial_balance, seed=42)
            print(f"  Profitable: {mc_results['profitable_pct']:.1%}")
            print(f"  Ruin risk: {mc_results['ruin_pct']:.1%}")
            print(f"  Median balance: ${mc_results['median_final_balance']:.2f}")
            write_json_report(
                os.path.join(VALIDATION_DIR, "monte-carlo.json"), mc_results)

        # ── Walk-Forward ─────────────────────────────────────────
        if not args["monte_carlo_only"] and not args["param_scan_only"]:
            print(f"\nRunning walk-forward analysis...")
            wf_results = walk_forward_analysis(
                candle_data, symbols, rules, edu_sections)
            if wf_results.get("windows"):
                print(f"  {wf_results['total_windows']} windows, "
                      f"{wf_results['profitable_windows']} profitable "
                      f"({wf_results['consistency_pct']:.0%})")
            else:
                print(f"  {wf_results.get('error', 'No windows generated')}")
            write_json_report(
                os.path.join(VALIDATION_DIR, "walk-forward.json"), wf_results)

        # ── Parameter Scan ───────────────────────────────────────
        if not args["monte_carlo_only"] and not args["walk_forward_only"]:
            print(f"\nRunning parameter scan (175 combinations)...")
            param_results = parameter_scan(
                candle_data, symbols, edu_sections,
                args["start"], args["end"])
            print(f"  Positive Sharpe: {param_results['positive_sharpe_count']}/175")
            print(f"  Stable plateau: {param_results['stable_count']}")
            if param_results.get("best_stable"):
                b = param_results["best_stable"]
                print(f"  Best: RR={b['rr_ratio']}, Risk={b['max_risk']:.1%}, "
                      f"LB={b['lookback']}, Sharpe={b['sharpe']:.2f}")
            # Save grid without full details for size
            write_json_report(
                os.path.join(VALIDATION_DIR, "parameter-scan.json"),
                {k: v for k, v in param_results.items() if k != "grid"})

        # ── Regime Analysis ──────────────────────────────────────
        if not args["monte_carlo_only"] and not args["walk_forward_only"] and not args["param_scan_only"]:
            print(f"\nRunning regime analysis...")
            regime_trades = segment_by_regime(result.trades, candle_data)
            regime_results = compute_regime_metrics(regime_trades)
            for regime, m in sorted(regime_results.items()):
                print(f"  {regime}: {m['count']} trades, WR={m['win_rate']:.0%}, E=${m['expectancy']:.2f}")

    # ── Write reports ────────────────────────────────────────────
    report_data = {
        "generated": datetime.now().isoformat(),
        "config": config_info,
        "metrics": metrics,
        "thresholds": THRESHOLDS,
    }
    if mc_results:
        report_data["monte_carlo"] = mc_results
    if wf_results:
        report_data["walk_forward"] = {k: v for k, v in wf_results.items() if k != "windows"}
    if param_results:
        report_data["parameter_scan"] = {k: v for k, v in param_results.items() if k != "grid"}
    if regime_results:
        report_data["regime_analysis"] = regime_results

    # Pass/fail
    passes = {
        "trades": metrics["total_trades"] >= THRESHOLDS["min_trades"],
        "sharpe": metrics["sharpe_ratio"] >= THRESHOLDS["min_sharpe"],
        "profit_factor": metrics["profit_factor"] >= THRESHOLDS["min_profit_factor"],
        "drawdown": metrics["max_drawdown_pct"] <= THRESHOLDS["max_drawdown_pct"],
        "win_rate": metrics["win_rate"] >= THRESHOLDS["min_win_rate"],
        "expectancy": metrics["expectancy_dollars"] > THRESHOLDS["min_expectancy_dollars"],
    }
    if mc_results:
        passes["monte_carlo"] = mc_results["profitable_pct"] >= THRESHOLDS["mc_profitable_pct"]
        passes["ruin_risk"] = mc_results["ruin_pct"] <= THRESHOLDS["mc_ruin_pct_max"]
    passes["overall"] = all(passes.values())
    report_data["pass_fail"] = passes

    write_json_report(os.path.join(VALIDATION_DIR, "validation-report.json"), report_data)

    md_path = write_markdown_report(
        metrics, mc_results, wf_results, param_results, regime_results, config_info)

    verdict = "PASS" if passes["overall"] else "FAIL"
    print(f"\n{'='*50}")
    print(f"  VERDICT: {verdict}")
    print(f"  Report: {md_path}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
