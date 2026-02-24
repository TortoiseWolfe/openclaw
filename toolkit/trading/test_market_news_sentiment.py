#!/usr/bin/env python3
"""Tests for market_news_sentiment.py — pure functions only, no API calls."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from market_news_sentiment import (
    build_ticker_batches,
    classify_sentiment,
    extract_ticker_sentiments,
    build_forex_pair_sentiments,
    build_market_summary,
    format_markdown_section,
)


# -- Mock data --------------------------------------------------------

MOCK_WATCHLIST = {
    "forex": [
        {"symbol": "EURUSD", "from": "EUR", "to": "USD"},
        {"symbol": "USDJPY", "from": "USD", "to": "JPY"},
    ],
    "stocks": [
        {"symbol": "AAPL"},
        {"symbol": "MSFT"},
        {"symbol": "NVDA"},
        {"symbol": "GOOGL"},
    ],
    "crypto": [
        {"symbol": "BTC", "market": "USD"},
    ],
}

MOCK_AV_RESPONSE = {
    "feed": [
        {
            "title": "Apple beats earnings",
            "url": "https://example.com/1",
            "time_published": "20260217T100000",
            "ticker_sentiment": [
                {"ticker": "AAPL", "ticker_sentiment_score": "0.30",
                 "ticker_sentiment_label": "Somewhat_Bullish",
                 "relevance_score": "0.90"},
                {"ticker": "MSFT", "ticker_sentiment_score": "0.10",
                 "ticker_sentiment_label": "Neutral",
                 "relevance_score": "0.30"},
            ],
        },
        {
            "title": "Tech sector rally continues",
            "url": "https://example.com/2",
            "time_published": "20260217T110000",
            "ticker_sentiment": [
                {"ticker": "AAPL", "ticker_sentiment_score": "0.20",
                 "ticker_sentiment_label": "Somewhat_Bullish",
                 "relevance_score": "0.70"},
                {"ticker": "NVDA", "ticker_sentiment_score": "0.40",
                 "ticker_sentiment_label": "Bullish",
                 "relevance_score": "0.95"},
            ],
        },
        {
            "title": "Market downturn fears",
            "url": "https://example.com/3",
            "time_published": "20260217T120000",
            "ticker_sentiment": [
                {"ticker": "MSFT", "ticker_sentiment_score": "-0.25",
                 "ticker_sentiment_label": "Somewhat_Bearish",
                 "relevance_score": "0.80"},
            ],
        },
    ],
}


# -- Tests ------------------------------------------------------------

class TestClassifySentiment(unittest.TestCase):
    def test_bearish(self):
        self.assertEqual(classify_sentiment(-0.50), "Bearish")
        self.assertEqual(classify_sentiment(-0.35), "Bearish")

    def test_somewhat_bearish(self):
        self.assertEqual(classify_sentiment(-0.20), "Somewhat_Bearish")
        self.assertEqual(classify_sentiment(-0.15), "Somewhat_Bearish")

    def test_neutral(self):
        self.assertEqual(classify_sentiment(0.0), "Neutral")
        self.assertEqual(classify_sentiment(0.10), "Neutral")
        self.assertEqual(classify_sentiment(-0.14), "Neutral")

    def test_somewhat_bullish(self):
        self.assertEqual(classify_sentiment(0.15), "Somewhat_Bullish")
        self.assertEqual(classify_sentiment(0.25), "Somewhat_Bullish")

    def test_bullish(self):
        self.assertEqual(classify_sentiment(0.35), "Bullish")
        self.assertEqual(classify_sentiment(0.50), "Bullish")

    def test_none(self):
        self.assertEqual(classify_sentiment(None), "No Data")


class TestBuildTickerBatches(unittest.TestCase):
    def test_correct_prefixes(self):
        batches = build_ticker_batches(MOCK_WATCHLIST)
        all_tickers = [t for batch in batches for t in batch]
        # Crypto should have CRYPTO: prefix
        crypto = [t for t in all_tickers if t.startswith("CRYPTO:")]
        self.assertEqual(len(crypto), 1)
        self.assertIn("CRYPTO:BTC", crypto)
        # Forex should have FOREX: prefix
        forex = [t for t in all_tickers if t.startswith("FOREX:")]
        self.assertGreater(len(forex), 0)
        self.assertIn("FOREX:EUR", forex)
        self.assertIn("FOREX:USD", forex)
        self.assertIn("FOREX:JPY", forex)

    def test_stocks_bare(self):
        batches = build_ticker_batches(MOCK_WATCHLIST)
        all_tickers = [t for batch in batches for t in batch]
        self.assertIn("AAPL", all_tickers)
        self.assertIn("MSFT", all_tickers)

    def test_no_empty_batches(self):
        batches = build_ticker_batches(MOCK_WATCHLIST)
        for batch in batches:
            self.assertGreater(len(batch), 0)

    def test_all_symbols_covered(self):
        batches = build_ticker_batches(MOCK_WATCHLIST)
        all_tickers = [t for batch in batches for t in batch]
        # 4 stocks + 1 crypto + 3 unique forex currencies = 8
        self.assertEqual(len(all_tickers), 8)


class TestExtractTickerSentiments(unittest.TestCase):
    def test_article_counts(self):
        result = extract_ticker_sentiments(MOCK_AV_RESPONSE)
        self.assertEqual(result["AAPL"]["article_count"], 2)
        self.assertEqual(result["MSFT"]["article_count"], 2)
        self.assertEqual(result["NVDA"]["article_count"], 1)

    def test_relevance_weighted_average(self):
        result = extract_ticker_sentiments(MOCK_AV_RESPONSE)
        # AAPL: (0.30*0.90 + 0.20*0.70) / (0.90+0.70) = 0.41/1.60 = 0.25625
        self.assertAlmostEqual(result["AAPL"]["avg_sentiment"], 0.2563, places=3)

    def test_sentiment_labels(self):
        result = extract_ticker_sentiments(MOCK_AV_RESPONSE)
        self.assertEqual(result["NVDA"]["sentiment_label"], "Bullish")

    def test_bullish_bearish_counts(self):
        result = extract_ticker_sentiments(MOCK_AV_RESPONSE)
        self.assertEqual(result["AAPL"]["bullish_count"], 2)
        self.assertEqual(result["AAPL"]["bearish_count"], 0)
        self.assertEqual(result["MSFT"]["bearish_count"], 1)

    def test_top_articles_capped(self):
        result = extract_ticker_sentiments(MOCK_AV_RESPONSE)
        for ticker in result:
            self.assertLessEqual(
                len(result[ticker]["top_articles"]), 3)

    def test_empty_feed(self):
        result = extract_ticker_sentiments({"feed": []})
        self.assertEqual(result, {})

    def test_missing_feed(self):
        result = extract_ticker_sentiments({})
        self.assertEqual(result, {})


class TestBuildForexPairSentiments(unittest.TestCase):
    def test_pair_computation(self):
        sentiments = {
            "FOREX:EUR": {"avg_sentiment": 0.10, "article_count": 5},
            "FOREX:USD": {"avg_sentiment": -0.05, "article_count": 8},
            "FOREX:JPY": {"avg_sentiment": 0.02, "article_count": 3},
        }
        pairs = build_forex_pair_sentiments(sentiments, MOCK_WATCHLIST)
        # EURUSD = EUR(0.10) - USD(-0.05) = 0.15
        self.assertAlmostEqual(pairs["EURUSD"]["net_sentiment"], 0.15)
        # USDJPY = USD(-0.05) - JPY(0.02) = -0.07
        self.assertAlmostEqual(pairs["USDJPY"]["net_sentiment"], -0.07)

    def test_missing_currency(self):
        sentiments = {"FOREX:EUR": {"avg_sentiment": 0.10, "article_count": 5}}
        pairs = build_forex_pair_sentiments(sentiments, MOCK_WATCHLIST)
        self.assertIsNone(pairs["EURUSD"]["net_sentiment"])
        self.assertEqual(pairs["EURUSD"]["net_label"], "No Data")


class TestBuildMarketSummary(unittest.TestCase):
    def test_basic_summary(self):
        sentiments = {
            "AAPL": {"article_count": 5, "avg_sentiment": 0.20},
            "MSFT": {"article_count": 3, "avg_sentiment": -0.10},
            "NVDA": {"article_count": 8, "avg_sentiment": 0.40},
        }
        summary = build_market_summary(sentiments)
        self.assertEqual(summary["total_articles"], 16)
        self.assertEqual(summary["most_bullish"], "NVDA")
        self.assertEqual(summary["most_bearish"], "MSFT")

    def test_empty(self):
        summary = build_market_summary({})
        self.assertEqual(summary["total_articles"], 0)
        self.assertEqual(summary["overall_label"], "No Data")

    def test_min_articles_for_ranking(self):
        sentiments = {
            "AAPL": {"article_count": 1, "avg_sentiment": -0.50},
            "NVDA": {"article_count": 5, "avg_sentiment": 0.30},
        }
        summary = build_market_summary(sentiments)
        # AAPL has only 1 article, shouldn't qualify for most_bearish
        self.assertEqual(summary["most_bearish"], "NVDA")


class TestFormatMarkdownSection(unittest.TestCase):
    def test_contains_header(self):
        data = {
            "symbols": {"AAPL": {"article_count": 5, "avg_sentiment": 0.20,
                                  "sentiment_label": "Somewhat_Bullish"}},
            "forex_pairs": {},
            "market_summary": {"total_articles": 5, "overall_sentiment": 0.20,
                               "overall_label": "Somewhat_Bullish",
                               "most_bullish": "AAPL", "most_bearish": None},
        }
        lines = format_markdown_section(data)
        self.assertEqual(lines[0], "## News Sentiment")

    def test_symbol_table(self):
        data = {
            "symbols": {"NVDA": {"article_count": 3, "avg_sentiment": 0.35,
                                  "sentiment_label": "Bullish"}},
            "forex_pairs": {},
            "market_summary": {"total_articles": 3, "overall_sentiment": 0.35,
                               "overall_label": "Bullish",
                               "most_bullish": "NVDA", "most_bearish": None},
        }
        lines = format_markdown_section(data)
        text = "\n".join(lines)
        self.assertIn("NVDA", text)
        self.assertIn("Bullish", text)

    def test_empty_data(self):
        data = {"symbols": {}, "forex_pairs": {}, "market_summary": {}}
        lines = format_markdown_section(data)
        self.assertEqual(lines[0], "## News Sentiment")


if __name__ == "__main__":
    unittest.main()
