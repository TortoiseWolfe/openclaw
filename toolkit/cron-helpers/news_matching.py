#!/usr/bin/env python3
"""Symbol matching and headline sentiment for news processing.

Shared utilities used by news_rss, news_babypips, news_hackernews,
and the market_news_supplementary orchestrator.
"""

import re

# ── Symbol name mappings ─────────────────────────────────────────────

SYMBOL_NAMES = {
    "AAPL": ["Apple", "iPhone", "iPad"],
    "MSFT": ["Microsoft", "Azure"],
    "NVDA": ["Nvidia", "GeForce", "CUDA"],
    "GOOGL": ["Google", "Alphabet", "Waymo"],
    "AMZN": ["Amazon", "AWS"],
    "AMD": ["Ryzen", "Radeon"],
    "PLTR": ["Palantir"],
    "AVGO": ["Broadcom"],
    "TSM": ["TSMC", "Taiwan Semiconductor"],
    "META": ["Facebook", "Instagram", "WhatsApp"],
    "ARM": ["Arm Holdings"],
    "SMCI": ["Super Micro", "Supermicro"],
    "CRM": ["Salesforce"],
    "MRVL": ["Marvell"],
    "DELL": ["Dell Technologies", "Dell Inc"],
    "AI": ["C3.ai", "C3 AI"],
    "PATH": ["UiPath"],
    "SNOW": ["Snowflake"],
    "SPY": ["S&P 500", "S&P500"],
    "QQQ": ["Nasdaq-100", "Nasdaq 100"],
    "BTC": ["Bitcoin"],
    "ETH": ["Ethereum", "Ether"],
    "EURUSD": ["EUR/USD", "euro dollar"],
    "GBPUSD": ["GBP/USD", "pound dollar", "cable"],
    "USDJPY": ["USD/JPY", "dollar yen"],
    "USDCHF": ["USD/CHF", "dollar franc"],
    "EURJPY": ["EUR/JPY", "euro yen"],
    "GBPJPY": ["GBP/JPY", "pound yen"],
    "AUDUSD": ["AUD/USD", "aussie dollar"],
}

# Short symbols that need case-sensitive matching to avoid false positives
_CASE_SENSITIVE_SYMBOLS = {
    "ARM", "META", "AMD", "CRM", "SPY",
    "PATH", "SNOW", "DELL",  # common English words
}
# Symbols matched ONLY via aliases (bare ticker too ambiguous)
_ALIAS_ONLY_SYMBOLS = {"AI"}

BULLISH_WORDS = [
    "surge", "rally", "beats", "upgrade", "record", "soar", "gain",
    "bullish", "outperform", "breakout", "boom", "strong", "growth",
    "profit", "buy", "upside", "optimistic", "momentum", "higher",
]

BEARISH_WORDS = [
    "crash", "plunge", "miss", "downgrade", "fears", "fall", "drop",
    "bearish", "underperform", "breakdown", "bust", "weak", "decline",
    "loss", "sell", "downside", "pessimistic", "slump", "recession",
    "lower",
]

MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5MB cap on HTTP responses

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
}


def build_symbol_set(watchlist):
    """Build set of all tracked symbols from watchlist."""
    symbols = set()
    for asset_class in ["forex", "stocks", "crypto"]:
        for asset in watchlist.get(asset_class, []):
            symbols.add(asset["symbol"])
    return symbols


def match_symbols(text, watchlist_symbols):
    """Match text against watchlist symbols and their aliases.

    Returns sorted list of matched symbol strings.
    """
    if not text:
        return []
    matched = set()

    for symbol in watchlist_symbols:
        aliases = SYMBOL_NAMES.get(symbol, [])

        # Some tickers are too ambiguous to match bare (e.g. "AI")
        if symbol not in _ALIAS_ONLY_SYMBOLS:
            if symbol in _CASE_SENSITIVE_SYMBOLS:
                if re.search(r'\b' + re.escape(symbol) + r'\b', text):
                    matched.add(symbol)
                    continue
            else:
                if re.search(r'\b' + re.escape(symbol) + r'\b', text,
                             re.IGNORECASE):
                    matched.add(symbol)
                    continue

        for alias in aliases:
            if re.search(r'\b' + re.escape(alias) + r'\b', text,
                         re.IGNORECASE):
                matched.add(symbol)
                break

    return sorted(matched)


def headline_sentiment(text):
    """Crude headline sentiment from keyword counting.

    Returns "bullish", "bearish", or "neutral".
    """
    if not text:
        return "neutral"
    text_lower = text.lower()
    bull = sum(1 for w in BULLISH_WORDS
               if re.search(r'\b' + w + r'\b', text_lower))
    bear = sum(1 for w in BEARISH_WORDS
               if re.search(r'\b' + w + r'\b', text_lower))
    if bull > bear:
        return "bullish"
    if bear > bull:
        return "bearish"
    return "neutral"
