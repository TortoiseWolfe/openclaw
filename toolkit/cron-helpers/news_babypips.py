#!/usr/bin/env python3
"""BabyPips daily forex recap fetcher.

Fetches the daily market recap from BabyPips, extracts forex pair mentions,
currency strength signals, and economic event references.
"""

import re
import sys
import urllib.request
from datetime import timedelta

from content_security import detect_suspicious, sanitize_field
from forex_education import ContentExtractor
from news_matching import _HEADERS, MAX_RESPONSE_BYTES

BABYPIPS_URL_TEMPLATE = (
    "https://www.babypips.com/news/"
    "daily-forex-financial-market-news-recap-{date}"
)

FOREX_CURRENCIES = ["EUR", "USD", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"]
FOREX_PAIR_PATTERN = re.compile(
    r'\b(' + '|'.join(FOREX_CURRENCIES) + r')[/ ]?('
    + '|'.join(FOREX_CURRENCIES) + r')\b',
    re.IGNORECASE,
)

_STANDARD_PAIRS = {
    "EURUSD", "GBPUSD", "AUDUSD", "NZDUSD",
    "USDJPY", "USDCHF", "USDCAD",
    "EURJPY", "EURGBP", "EURAUD", "EURCHF", "EURCAD", "EURNZD",
    "GBPJPY", "GBPAUD", "GBPCHF", "GBPCAD", "GBPNZD",
    "AUDJPY", "AUDCHF", "AUDCAD", "AUDNZD",
    "NZDJPY", "NZDCHF", "NZDCAD",
    "CADJPY", "CADCHF",
    "CHFJPY",
}

DIRECTIONAL_BULLISH = re.compile(
    r'\b(bullish|rally|support|bounce|upside|higher|strong|surge)\b', re.I)
DIRECTIONAL_BEARISH = re.compile(
    r'\b(bearish|sell-off|resistance|decline|downside|lower|weak|drop)\b',
    re.I)

ECON_EVENT_PATTERNS = [
    re.compile(r'\b(rate decision|interest rate|monetary policy)\b', re.I),
    re.compile(r'\b(GDP|gross domestic product)\b', re.I),
    re.compile(r'\b(employment|jobs|NFP|non-farm|payroll)\b', re.I),
    re.compile(r'\b(CPI|inflation|consumer price)\b', re.I),
    re.compile(r'\b(PMI|manufacturing|services index)\b', re.I),
    re.compile(r'\b(retail sales)\b', re.I),
    re.compile(r'\b(central bank|Fed|ECB|BOJ|BOE|RBA|SNB|BOC|RBNZ)\b', re.I),
]


def _normalize_pair(base, quote):
    """Normalize a forex pair to standard order."""
    pair = f"{base}{quote}"
    if pair in _STANDARD_PAIRS:
        return pair
    flipped = f"{quote}{base}"
    if flipped in _STANDARD_PAIRS:
        return flipped
    return pair


def fetch_babypips_recap(today):
    """Fetch BabyPips daily forex recap.

    Tries today, yesterday, 2-days-ago. Returns dict with fetched,
    pairs_mentioned, currency_strength, economic_events, key_headlines.
    """
    result = {
        "fetched": False,
        "pairs_mentioned": [],
        "currency_strength": {},
        "economic_events": [],
        "key_headlines": [],
        "error": None,
    }

    for days_back in range(3):
        try_date = today - timedelta(days=days_back)
        url = BABYPIPS_URL_TEMPLATE.format(date=try_date.isoformat())

        try:
            req = urllib.request.Request(url, headers={
                **_HEADERS,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                html = resp.read(MAX_RESPONSE_BYTES).decode(charset)

            parser = ContentExtractor()
            parser.feed(html)
            content = parser.get_content(max_words=3000)

            if len(content.split()) < 50:
                continue

            flags = detect_suspicious(content)
            if flags:
                print(f"  [security] BabyPips suspicious: {flags}",
                      file=sys.stderr)
                result["error"] = f"Suspicious content: {flags}"
                continue

            result["fetched"] = True
            result["fetch_date"] = try_date.isoformat()

            # Extract forex pair mentions
            pairs = set()
            for m in FOREX_PAIR_PATTERN.finditer(content):
                base = m.group(1).upper()
                quote = m.group(2).upper()
                if base != quote:
                    pairs.add(_normalize_pair(base, quote))
            result["pairs_mentioned"] = sorted(pairs)

            # Currency strength from directional language
            currency_bull = {}
            currency_bear = {}
            for curr in FOREX_CURRENCIES:
                curr_pat = re.compile(
                    r'[^.]*\b' + curr + r'\b[^.]*\.', re.I)
                for sentence in curr_pat.findall(content):
                    if DIRECTIONAL_BULLISH.search(sentence):
                        currency_bull[curr] = \
                            currency_bull.get(curr, 0) + 1
                    if DIRECTIONAL_BEARISH.search(sentence):
                        currency_bear[curr] = \
                            currency_bear.get(curr, 0) + 1

            net_strength = {}
            for curr in set(list(currency_bull) + list(currency_bear)):
                net_strength[curr] = (currency_bull.get(curr, 0)
                                      - currency_bear.get(curr, 0))
            if net_strength:
                result["currency_strength"] = {
                    "strongest": max(net_strength,
                                     key=net_strength.get),
                    "weakest": min(net_strength,
                                   key=net_strength.get),
                    "detail": net_strength,
                }

            # Extract economic events
            events = set()
            for pat in ECON_EVENT_PATTERNS:
                for m in pat.finditer(content):
                    events.add(m.group(0))
            result["economic_events"] = sorted(events)

            # Key headlines: first substantive sentences
            sentences = re.split(r'(?<=[.!?])\s+', content)
            result["key_headlines"] = [
                sanitize_field(s, max_len=200)
                for s in sentences[:5] if len(s) > 20
            ]

            print(f"  BabyPips: fetched recap for "
                  f"{try_date.isoformat()}")
            return result

        except Exception as e:
            if days_back == 2:
                result["error"] = str(e)
                print(f"  BabyPips: FAILED all attempts ({e})",
                      file=sys.stderr)

    return result
