# Live Trading Roadmap

## Current State (Feb 2026)

Paper trading system running via daily cron jobs. Generates signals across
33 symbols (7 forex, 20 stocks, 6 crypto), manages positions in
`private/paper-state.json`.

**Backtest (2015-2025):** 2,926 trades, $10K -> $263K, Sharpe 0.69, PF 1.18,
42% win rate, 44% max drawdown. CONDITIONAL PASS validation.

**Paper trading:** Started Feb 13, ~12 trades so far. 10 position slots,
targeting ~8-10 trades/week.

## Phase 1: Paper Trading Validation (now - April 2026)

**Goal:** 50+ paper trades to confirm live signals match backtest behavior.

- [ ] Accumulate 50+ closed paper trades (Gate 1)
- [ ] Compare live win rate, PF, avg R:R to backtest expectations
- [ ] Monitor consecutive loss streaks (threshold: 40)
- [ ] Track signal-to-fill time (are signals stale by execution?)
- [ ] Re-run full validation monthly with updated data

**Exit criteria:** 50+ trades, positive expectancy, no red flags in
streak length or signal quality.

## Phase 2: Broker Selection & Paper Mode (April - May 2026)

**Goal:** Pick a broker, connect via API, run in broker paper mode.

### Broker Shortlist

| Broker | Assets | Minimum | API | Why |
|--------|--------|---------|-----|-----|
| **Interactive Brokers** | Stocks + forex + crypto | $0 | REST + WebSocket | Only multi-asset option. Micro forex lots. |
| **Alpaca** | Stocks only | $0 | REST | Commission-free, built for algo trading. Same API for paper + live. |
| **OANDA** | Forex only | $0 | REST | No minimum, micro lots, clean API. |

**Recommendation:** Start with **Alpaca** (stocks only). Lowest risk, free
paper trading mode, same API for paper and live. Add OANDA for forex later
if stocks perform well.

### Engineering Work

- [ ] Broker API client module (`toolkit/trading/broker_client.py`)
  - Authentication (OAuth / API key)
  - Submit market orders
  - Query positions and fills
  - Account balance and margin
- [ ] Order management layer (`toolkit/trading/order_manager.py`)
  - Convert paper-state signals to broker orders
  - Handle partial fills, rejections, retries
  - Map broker position state back to local tracking
- [ ] Risk controls (`toolkit/trading/risk_guard.py`)
  - Kill switch (disable trading if daily loss > X%)
  - Max position count enforcement (redundant with broker, but local check)
  - Connectivity check before order submission
  - Cooldown after N consecutive losses
- [ ] Monitoring / alerts
  - Order fill confirmation vs expected price (slippage tracking)
  - Position divergence alerts (local state vs broker state)
  - Daily P&L summary to agent session

### Architecture

```
market_trade_decision.py (existing)
  |
  v
order_manager.py (new) --- broker_client.py (new)
  |                              |
  v                              v
paper-state.json (existing)    Broker API (Alpaca/IBKR/OANDA)
  |
  v
risk_guard.py (new) --- kills trading if limits breached
```

The existing `market_trade_decision.py` already produces entry/exit
decisions. The new layer translates those into broker API calls while
keeping `paper-state.json` as the local record of truth.

## Phase 3: Live Trading - Small Scale (May - Aug 2026)

**Goal:** $1,000 real money, stocks only via Alpaca.

- [ ] Fund Alpaca account with $1,000
- [ ] Run broker paper mode for 1 week to verify order flow
- [ ] Switch to live with same $1,000
- [ ] Monitor daily: fills, slippage, P&L vs paper expectations
- [ ] Weekly: compare live metrics to backtest
- [ ] Monthly: full validation re-run

**Realistic expectations at $1K:**
- Good year (~20% return): $1,200
- Average year (~10%): $1,100
- Bad year (-20% to -40%): $600-$800
- Position sizes will be tiny — this is for confidence building, not returns

**Exit criteria:** 3 months of live trading without system failures,
slippage within modeled bounds, P&L trajectory plausible vs backtest.

## Phase 4: Scale Up (Aug 2026+)

Only after Phase 3 proves the system works with real money:

- [ ] Add forex via OANDA (or switch to IBKR for multi-asset)
- [ ] Increase capital gradually (double every quarter if metrics hold)
- [ ] Add crypto if regulations allow
- [ ] Consider moving to IBKR for unified multi-asset

## Risk Reminders

- The backtest Sharpe is 0.69, not 2.0. The edge is thin.
- 44% max drawdown means you WILL see your account cut nearly in half.
- 36 consecutive losses is the worst case. Plan for it mentally.
- $1K is learning money. Don't risk money you can't lose.
- Backtest != live. Slippage, timing, and psychology are different.
- The system was optimized on historical data — overfitting risk is real.
  Walk-forward shows 72% OOS profitability, which is encouraging but not proof.
