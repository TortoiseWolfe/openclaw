#!/usr/bin/env python3
"""Asset handler classes for forex, stocks, and crypto.

Each handler encapsulates pip/price calculations, position sizing,
P&L computation, and asset-class-specific behavior (e.g. weekend close).
"""

BUFFER_PIPS = 5  # stop-loss buffer beyond swing high/low


class ForexHandler:
    """Forex: pip-based P&L, lot-based sizing, weekend close."""

    def pip_size(self, symbol, config):
        return config.get("pip_size", 0.0001)

    def to_pips(self, symbol, config, diff):
        return round(diff / self.pip_size(symbol, config), 1)

    def _pip_value_usd(self, symbol, config, price, cross_rates=None):
        """Dollar value of 1 pip per standard lot (100K units).

        For USD-quote pairs (EURUSD, GBPUSD): always $10/pip/lot.
        For non-USD-quote pairs (USDJPY, EURJPY, etc.): pip value in
        quote currency converted to USD via the USD/quote cross rate.
        """
        if symbol.endswith("USD"):
            return 10.0
        pip = self.pip_size(symbol, config)
        # Use the USD cross rate for the quote currency when available
        # e.g. EURJPY → use USDJPY rate, EURCHF → use USDCHF rate
        quote_ccy = symbol[-3:]  # JPY, CHF, etc.
        usd_rate = None
        if cross_rates:
            usd_rate = cross_rates.get(f"USD{quote_ccy}")
        if usd_rate and usd_rate > 0:
            return (pip / usd_rate) * 100_000
        # Fallback: use the pair's own price (approximate)
        return (pip / price) * 100_000 if price > 0 else 10.0

    def position_size(self, balance, risk_pct, stop_distance, price, symbol, config,
                       cross_rates=None):
        stop_pips = abs(stop_distance) / self.pip_size(symbol, config)
        if stop_pips == 0:
            return 0
        pip_value = self._pip_value_usd(symbol, config, price, cross_rates)
        lots = (balance * risk_pct) / (stop_pips * pip_value)
        return round(lots * 100_000)  # nearest unit, not truncated

    def calculate_pnl(self, entry, exit_price, direction, size, symbol, config,
                       rules=None, cross_rates=None):
        # Apply spread: buy at ask, sell at bid
        if rules:
            half_spread = rules.get("spread", {}).get("forex", 0) / 2
            if direction == "LONG":
                entry = entry + half_spread
                exit_price = exit_price - half_spread
            else:
                entry = entry - half_spread
                exit_price = exit_price + half_spread
        if direction == "LONG":
            diff = exit_price - entry
        else:
            diff = entry - exit_price
        pips = diff / self.pip_size(symbol, config)
        lots = size / 100_000
        pip_value = self._pip_value_usd(symbol, config, exit_price, cross_rates)
        return pips * lots * pip_value  # full precision — round at display

    def format_size(self, size):
        return f"{size} units"

    def weekend_close(self):
        return True

    def stop_buffer(self, symbol, config, price=0):
        return BUFFER_PIPS * self.pip_size(symbol, config)


class StockHandler:
    """Stocks: dollar-based P&L, whole shares."""

    def to_pips(self, symbol, config, diff):
        return round(diff, 2)

    def position_size(self, balance, risk_pct, stop_distance, price, symbol, config,
                       cross_rates=None):
        if stop_distance == 0:
            return 0
        # Whole shares — round to nearest (real brokers floor, but rounding
        # is more accurate for paper trading and avoids systematic undersize)
        return round((balance * risk_pct) / abs(stop_distance))

    def calculate_pnl(self, entry, exit_price, direction, size, symbol, config,
                       rules=None, cross_rates=None):
        # Apply spread: buy at ask, sell at bid
        if rules:
            half_spread = rules.get("spread", {}).get("stocks", 0) / 2
            if direction == "LONG":
                entry = entry + half_spread
                exit_price = exit_price - half_spread
            else:
                entry = entry - half_spread
                exit_price = exit_price + half_spread
        if direction == "LONG":
            diff = exit_price - entry
        else:
            diff = entry - exit_price
        return diff * size  # full precision — round at display

    def format_size(self, size):
        return f"{size} shares"

    def weekend_close(self):
        return False

    def stop_buffer(self, symbol, config, price=0):
        return max(0.50, price * 0.005)  # 0.5% of price, min $0.50


class CryptoHandler:
    """Crypto: dollar-based P&L, fractional coins."""

    def to_pips(self, symbol, config, diff):
        return round(diff, 2)

    def position_size(self, balance, risk_pct, stop_distance, price, symbol, config,
                       cross_rates=None):
        if stop_distance == 0:
            return 0
        return round((balance * risk_pct) / abs(stop_distance), 8)

    def calculate_pnl(self, entry, exit_price, direction, size, symbol, config,
                       rules=None, cross_rates=None):
        # Apply spread: percentage-based for crypto
        if rules:
            half_pct = rules.get("spread", {}).get("crypto_pct", 0) / 2
            if direction == "LONG":
                entry = entry * (1 + half_pct)
                exit_price = exit_price * (1 - half_pct)
            else:
                entry = entry * (1 - half_pct)
                exit_price = exit_price * (1 + half_pct)
        if direction == "LONG":
            diff = exit_price - entry
        else:
            diff = entry - exit_price
        return diff * size  # full precision — round at display

    def format_size(self, size):
        return f"{size} coins"

    def weekend_close(self):
        return False

    def stop_buffer(self, symbol, config, price=1.0):
        # 1% of last price — works across BTC ($60K), SOL ($100), DOGE ($0.15)
        return price * 0.01


HANDLERS = {
    "forex": ForexHandler(),
    "stocks": StockHandler(),
    "crypto": CryptoHandler(),
}
