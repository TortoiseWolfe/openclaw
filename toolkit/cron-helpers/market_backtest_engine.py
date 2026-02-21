#!/usr/bin/env python3
"""Backtest engine — replays analyze() over historical candle data.

Imports signal logic from market_trade_decision.py and simulates trades
day by day. Tracks equity curve, position management, SL/TP exits.
Pure Python, no external dependencies.

Usage (from Docker):
  from market_backtest_engine import run_backtest, BacktestConfig
  result = run_backtest(config, candle_data)
"""

import json
import os
import sys
from datetime import date, datetime

# Allow importing siblings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import market_trade_decision as mtd
from trading_common import check_correlation_guard, CONFIG_DIR, DATA_DIR, HISTORICAL_DIR
from trading_handlers import HANDLERS
from trading_signals import LOOKBACK, analyze


# ── Configuration ─────────────────────────────────────────────────────

class BacktestConfig:
    """Parameters for a single backtest run."""

    def __init__(
        self,
        start_date="2015-01-01",
        end_date="2025-12-31",
        initial_balance=10000.0,
        max_risk=0.02,
        rr_ratio=1.5,
        max_positions_global=3,
        max_positions_per_class=None,
        edu_sections=None,
        edu_all_unlocked=True,
        lookback=10,
        symbols=None,
        spread=None,
        slippage=None,
    ):
        self.start_date = start_date
        self.end_date = end_date
        self.initial_balance = initial_balance
        self.max_risk = max_risk
        self.rr_ratio = rr_ratio
        self.max_positions_global = max_positions_global
        self.max_positions_per_class = max_positions_per_class or {
            "forex": 2, "stocks": 2, "crypto": 1,
        }
        # edu_all_unlocked=True (default): all signals generate regardless
        # of education — preserving historical backtest behavior.
        # Set False to test education gating impact.
        if edu_all_unlocked:
            self.edu_sections = {
                "Japanese Candlesticks", "Fibonacci", "Moving Averages",
                "Support and Resistance Levels", "Popular Chart Indicators",
                "Important Chart Patterns", "Risk Management", "Position Sizing",
                "Oscillators and Momentum Indicators", "Trading Divergences",
                "Pivot Points",
            }
        else:
            self.edu_sections = edu_sections if edu_sections is not None else set()
        self.lookback = lookback
        self.symbols = symbols  # [(asset_class, symbol, config_dict), ...]
        self.spread = spread or {}      # {"forex": 0.00015, "stocks": 0.02, "crypto_pct": 0.0015}
        self.slippage = slippage or {}  # {"forex": 0.00005, "stocks": 0.01, "crypto_pct": 0.0005}
        self.correlation_enabled = False  # Default off — preserves existing backtest behavior
        self.correlation_rules = None     # Set to {"forex_max_same_currency": 1, ...} to enable
        self.extra_rules = {}  # Additional rules passed through to analyze() (e.g., signal filters)


# ── Result ────────────────────────────────────────────────────────────

class BacktestResult:
    """Output of a single backtest run."""

    def __init__(self):
        self.trades = []          # All closed trades
        self.equity_curve = []    # [{date, balance}, ...]
        self.final_balance = 0.0
        self.max_drawdown_pct = 0.0

    def to_dict(self):
        return {
            "trade_count": len(self.trades),
            "final_balance": round(self.final_balance, 2),
            "trades": self.trades,
            "equity_curve_length": len(self.equity_curve),
        }


# ── Core Backtest Loop ────────────────────────────────────────────────

def run_backtest(config, candle_data):
    """Replay signal logic over historical candles.

    candle_data: {(asset_class, symbol): [candles sorted by date]}
    config: BacktestConfig instance

    Returns BacktestResult with all closed trades and equity curve.
    """
    import trading_signals
    # Override LOOKBACK if config specifies different value
    orig_lookback = trading_signals.LOOKBACK
    trading_signals.LOOKBACK = config.lookback

    try:
        return _run_backtest_inner(config, candle_data)
    finally:
        trading_signals.LOOKBACK = orig_lookback


def _run_backtest_inner(config, candle_data):
    result = BacktestResult()
    balance = config.initial_balance
    peak_balance = config.initial_balance
    open_positions = []
    next_id = 1

    rules = {
        "max_risk": config.max_risk,
        "rr_ratio": config.rr_ratio,
        "max_positions": {
            **config.max_positions_per_class,
            "global": config.max_positions_global,
        },
        "spread": config.spread,
        "slippage": config.slippage,
        **config.extra_rules,  # signal filters, ATR/ADX configs, etc.
    }
    if config.correlation_enabled and config.correlation_rules:
        rules["correlation"] = {
            "enabled": True,
            **config.correlation_rules,
        }

    # Build watchlist-shaped dict for correlation guard lookups
    bt_watchlist = {"forex": [], "stocks": [], "crypto": []}
    for ac, sym, cfg in (config.symbols or []):
        bt_watchlist.setdefault(ac, []).append(cfg)

    # Build sorted list of all unique trading dates
    all_dates = set()
    for candles in candle_data.values():
        for c in candles:
            if config.start_date <= c["date"] <= config.end_date:
                all_dates.add(c["date"])
    all_dates = sorted(all_dates)

    if not all_dates:
        result.final_balance = balance
        return result

    # Pre-index candles by date for fast lookup
    # candle_index[(ac, sym)][date] = index into candle list
    candle_index = {}
    for key, candles in candle_data.items():
        idx = {}
        for i, c in enumerate(candles):
            idx[c["date"]] = i
        candle_index[key] = idx

    symbols = config.symbols or []

    for today in all_dates:
        # Parse weekday (0=Mon, 4=Fri)
        dt = datetime.strptime(today, "%Y-%m-%d")
        is_friday = dt.weekday() == 4

        # ── Check SL/TP on open positions ────────────────────────
        still_open = []
        for pos in open_positions:
            key = (pos["asset_class"], pos["symbol"])
            candles = candle_data.get(key, [])
            idx_map = candle_index.get(key, {})
            ci = idx_map.get(today)

            if ci is None:
                still_open.append(pos)
                continue

            candle = candles[ci]
            handler = HANDLERS[pos["asset_class"]]
            closed = False

            if pos["direction"] == "LONG":
                # Check SL first (conservative: assume adverse hit first)
                if candle["l"] <= pos["stop_loss"]:
                    exit_price = pos["stop_loss"]
                    pnl = handler.calculate_pnl(
                        pos["entry"], exit_price, "LONG", pos["size"],
                        pos["symbol"], pos["config"], rules=rules)
                    _close_trade(pos, exit_price, pnl, today, "stop_loss", result)
                    balance += pnl
                    closed = True
                elif candle["h"] >= pos["take_profit"]:
                    exit_price = pos["take_profit"]
                    pnl = handler.calculate_pnl(
                        pos["entry"], exit_price, "LONG", pos["size"],
                        pos["symbol"], pos["config"], rules=rules)
                    _close_trade(pos, exit_price, pnl, today, "take_profit", result)
                    balance += pnl
                    closed = True
            else:  # SHORT
                if candle["h"] >= pos["stop_loss"]:
                    exit_price = pos["stop_loss"]
                    pnl = handler.calculate_pnl(
                        pos["entry"], exit_price, "SHORT", pos["size"],
                        pos["symbol"], pos["config"], rules=rules)
                    _close_trade(pos, exit_price, pnl, today, "stop_loss", result)
                    balance += pnl
                    closed = True
                elif candle["l"] <= pos["take_profit"]:
                    exit_price = pos["take_profit"]
                    pnl = handler.calculate_pnl(
                        pos["entry"], exit_price, "SHORT", pos["size"],
                        pos["symbol"], pos["config"], rules=rules)
                    _close_trade(pos, exit_price, pnl, today, "take_profit", result)
                    balance += pnl
                    closed = True

            if not closed:
                still_open.append(pos)

        open_positions = still_open

        # ── Friday forex close ───────────────────────────────────
        if is_friday:
            still_open = []
            for pos in open_positions:
                if HANDLERS[pos["asset_class"]].weekend_close():
                    key = (pos["asset_class"], pos["symbol"])
                    candles = candle_data.get(key, [])
                    idx_map = candle_index.get(key, {})
                    ci = idx_map.get(today)
                    if ci is not None:
                        exit_price = candles[ci]["c"]
                    else:
                        exit_price = pos["entry"]  # fallback
                    handler = HANDLERS[pos["asset_class"]]
                    pnl = handler.calculate_pnl(
                        pos["entry"], exit_price, pos["direction"],
                        pos["size"], pos["symbol"], pos["config"], rules=rules)
                    _close_trade(pos, exit_price, pnl, today, "weekend_close", result)
                    balance += pnl
                else:
                    still_open.append(pos)
            open_positions = still_open

        # Update peak balance (high-water mark)
        if balance > peak_balance:
            peak_balance = balance

        # Drawdown circuit breaker: halt new entries if DD exceeds limit
        max_dd_limit = rules.get("max_drawdown", 1.0)
        current_dd = (peak_balance - balance) / peak_balance if peak_balance > 0 else 0
        halt_new_entries = current_dd > max_dd_limit

        # ── Generate signals and open new trades ─────────────────
        # Equity curve filter: reduce max positions during losing streaks
        effective_max_global = config.max_positions_global
        ecf = rules.get("equity_curve_filter", {})
        if ecf.get("enabled", False):
            lb = ecf.get("lookback_trades", 10)
            recent = result.trades[-lb:] if len(result.trades) >= lb else []
            if len(recent) >= lb:
                recent_pnl = sum(t.get("pnl_dollars", 0) for t in recent)
                if recent_pnl < 0:
                    effective_max_global = min(
                        effective_max_global,
                        ecf.get("reduced_max_positions", 3))

        if halt_new_entries:
            effective_max_global = 0

        for asset_class, symbol, sym_config in symbols:
            key = (asset_class, symbol)
            candles = candle_data.get(key, [])
            idx_map = candle_index.get(key, {})
            ci = idx_map.get(today)
            if ci is None:
                continue

            # Need at least lookback candles before today
            if ci < config.lookback:
                continue

            # Position limits
            if len(open_positions) >= effective_max_global:
                break
            class_count = sum(
                1 for p in open_positions if p["asset_class"] == asset_class)
            class_max = config.max_positions_per_class.get(asset_class, 2)
            if class_count >= class_max:
                continue

            # No duplicate symbols
            if any(p["symbol"] == symbol for p in open_positions):
                continue

            # Slice candles up to and including today
            candle_slice = candles[:ci + 1]

            analysis = analyze(
                asset_class, symbol, sym_config,
                candle_slice, config.edu_sections, rules)

            if analysis is None or analysis.get("signal") is None:
                continue

            sig = analysis["signal"]

            # Correlation guard (opt-in via config)
            if config.correlation_enabled and config.correlation_rules:
                corr_ok, _ = check_correlation_guard(
                    asset_class, symbol, sig["direction"],
                    sym_config, open_positions, rules, bt_watchlist)
                if not corr_ok:
                    continue

            handler = HANDLERS[asset_class]

            # Apply slippage: adverse entry + widened stop
            slip_cfg = config.slippage
            if asset_class == "crypto":
                slip = sig["entry"] * slip_cfg.get("crypto_pct", 0)
            else:
                slip = slip_cfg.get(asset_class, 0)

            if sig["direction"] == "LONG":
                entry = sig["entry"] + slip
                stop_loss = sig["stop_loss"] - slip
            else:
                entry = sig["entry"] - slip
                stop_loss = sig["stop_loss"] + slip
            take_profit = sig["take_profit"]

            stop_dist = abs(entry - stop_loss)
            if stop_dist <= 0:
                continue

            size = handler.position_size(
                balance, config.max_risk, stop_dist,
                entry, symbol, sym_config)
            if size <= 0:
                continue

            # Regime-based sizing: scale position by market regime
            regime_sizing = rules.get("regime_sizing", {})
            if regime_sizing.get("enabled", False):
                regime = analysis.get("regime", "unknown")
                regime_mult = regime_sizing.get("multipliers", {}).get(regime, 1.0)
                if regime_mult <= 0:
                    continue  # regime blocks entry
                if regime_mult != 1.0:
                    size = max(1, round(size * regime_mult))

            # Compute risk amount for R-multiple tracking
            risk_amount = abs(stop_dist) * size
            # For forex, convert to dollar risk
            if asset_class == "forex":
                pips = abs(stop_dist) / handler.pip_size(symbol, sym_config)
                lots = size / 100_000
                pip_val = handler._pip_value_usd(symbol, sym_config, entry)
                risk_amount = pips * lots * pip_val

            pos = {
                "id": f"BT{next_id}",
                "date_opened": today,
                "asset_class": asset_class,
                "symbol": symbol,
                "direction": sig["direction"],
                "entry": entry,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "size": size,
                "reason": sig["reason"],
                "config": sym_config,
                "risk_amount": risk_amount,
            }
            open_positions.append(pos)
            next_id += 1

        # ── Record equity curve point ────────────────────────────
        # Include unrealized P&L for accurate curve
        unrealized = 0.0
        for pos in open_positions:
            key = (pos["asset_class"], pos["symbol"])
            candles = candle_data.get(key, [])
            idx_map = candle_index.get(key, {})
            ci = idx_map.get(today)
            if ci is not None:
                handler = HANDLERS[pos["asset_class"]]
                price = candles[ci]["c"]
                unrealized += handler.calculate_pnl(
                    pos["entry"], price, pos["direction"],
                    pos["size"], pos["symbol"], pos["config"], rules=rules)

        result.equity_curve.append({
            "date": today,
            "balance": balance + unrealized,
        })

    # ── Force-close remaining at end ─────────────────────────────
    for pos in open_positions:
        key = (pos["asset_class"], pos["symbol"])
        candles = candle_data.get(key, [])
        if candles:
            exit_price = candles[-1]["c"]
        else:
            exit_price = pos["entry"]
        handler = HANDLERS[pos["asset_class"]]
        pnl = handler.calculate_pnl(
            pos["entry"], exit_price, pos["direction"],
            pos["size"], pos["symbol"], pos["config"], rules=rules)
        _close_trade(pos, exit_price, pnl, all_dates[-1], "end_of_test", result)
        balance += pnl

    result.final_balance = balance

    # Final equity point
    if result.equity_curve and result.equity_curve[-1]["date"] != all_dates[-1]:
        result.equity_curve.append({
            "date": all_dates[-1],
            "balance": balance,
        })

    return result


def _close_trade(pos, exit_price, pnl, close_date, close_reason, result):
    """Record a closed trade in the result."""
    risk = pos.get("risk_amount", 1.0)
    rr = pnl / risk if risk > 0 else 0.0

    result.trades.append({
        "id": pos["id"],
        "entry_date": pos["date_opened"],
        "close_date": close_date,
        "asset_class": pos["asset_class"],
        "symbol": pos["symbol"],
        "direction": pos["direction"],
        "entry": pos["entry"],
        "exit": exit_price,
        "stop_loss": pos["stop_loss"],
        "take_profit": pos["take_profit"],
        "size": pos["size"],
        "reason": pos["reason"],
        "pnl": round(pnl, 6),
        "rr_achieved": round(rr, 4),
        "close_reason": close_reason,
    })


# ── Candle Loading ────────────────────────────────────────────────────


def load_historical_candles(symbols, prefer_historical=True):
    """Load candle data for backtesting.

    symbols: [(asset_class, symbol, config_dict), ...]
    Returns {(asset_class, symbol): [candles sorted by date]}
    """
    candle_data = {}
    for asset_class, symbol, config in symbols:
        loaded = False
        # Try historical first (full 20-year data)
        if prefer_historical:
            hist_path = os.path.join(HISTORICAL_DIR, asset_class,
                                     f"{symbol}-daily.json")
            if os.path.exists(hist_path):
                candle_data[(asset_class, symbol)] = _load_candle_file(hist_path)
                loaded = True

        # Fall back to regular data directory
        if not loaded:
            reg_path = os.path.join(DATA_DIR, asset_class,
                                    f"{symbol}-daily.json")
            if os.path.exists(reg_path):
                candle_data[(asset_class, symbol)] = _load_candle_file(reg_path)

    return candle_data


def _load_candle_file(path):
    """Load and validate candles from a JSON file."""
    with open(path) as f:
        data = json.load(f)
    result = []
    for c in data["candles"]:
        o = float(c.get("o", 0))
        h = float(c.get("h", 0))
        l = float(c.get("l", 0))
        cl = float(c.get("c", 0))
        if any(v <= 0 for v in (o, h, l, cl)):
            continue
        result.append({"date": c["date"], "o": o, "h": h, "l": l, "c": cl})
    return result


def load_watchlist_symbols(watchlist_path=None):
    """Load symbols from watchlist.json for backtesting."""
    if watchlist_path is None:
        watchlist_path = os.path.join(CONFIG_DIR, "watchlist.json")
    with open(watchlist_path) as f:
        wl = json.load(f)

    symbols = []
    for asset_class in ["forex", "stocks", "crypto"]:
        for asset in wl.get(asset_class, []):
            symbols.append((asset_class, asset["symbol"], asset))

    rules = wl.get("rules", {})
    return symbols, rules
