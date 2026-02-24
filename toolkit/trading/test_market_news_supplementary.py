#!/usr/bin/env python3
"""Tests for market_news_supplementary.py — pure functions only, no network."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from market_news_supplementary import (
    match_symbols,
    headline_sentiment,
    parse_rss_xml,
    build_symbol_mentions,
    build_summary,
    format_supplementary_markdown,
    build_symbol_set,
    _normalize_pair,
    _escape_pipe,
)


# -- Mock data -----------------------------------------------------------

MOCK_WATCHLIST = {
    "forex": [
        {"symbol": "EURUSD", "from": "EUR", "to": "USD"},
        {"symbol": "USDJPY", "from": "USD", "to": "JPY"},
    ],
    "stocks": [
        {"symbol": "AAPL"},
        {"symbol": "NVDA"},
        {"symbol": "AI"},
        {"symbol": "ARM"},
        {"symbol": "META"},
        {"symbol": "AMD"},
        {"symbol": "CRM"},
        {"symbol": "GOOGL"},
        {"symbol": "PATH"},
        {"symbol": "SNOW"},
        {"symbol": "DELL"},
    ],
    "crypto": [
        {"symbol": "BTC", "market": "USD"},
    ],
}

MOCK_SYMBOLS = build_symbol_set(MOCK_WATCHLIST)

MOCK_RSS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Nvidia stock surges on record AI chip earnings</title>
      <link>https://example.com/1</link>
      <pubDate>Mon, 17 Feb 2026 10:00:00 GMT</pubDate>
      <description>NVDA beats expectations with strong GPU demand</description>
    </item>
    <item>
      <title>Apple reports mixed quarterly results</title>
      <link>https://example.com/2</link>
      <pubDate>Mon, 17 Feb 2026 11:00:00 GMT</pubDate>
      <description>iPhone sales decline while services revenue grows</description>
    </item>
    <item>
      <title>Oil prices steady amid OPEC talks</title>
      <link>https://example.com/3</link>
      <pubDate>Mon, 17 Feb 2026 12:00:00 GMT</pubDate>
      <description>Crude oil remains flat with no watchlist tickers</description>
    </item>
    <item>
      <link>https://example.com/4</link>
      <description>Item with no title should be skipped</description>
    </item>
  </channel>
</rss>"""

MOCK_RSS_DATA = {
    "feeds_attempted": 2,
    "feeds_succeeded": 2,
    "articles_found": 10,
    "articles_matched": 3,
    "matched": [
        {"title": "Nvidia surges", "url": "https://example.com/1",
         "source": "yahoo", "published": "Mon, 17 Feb 2026",
         "matched_symbols": ["NVDA"], "headline_sentiment": "bullish"},
        {"title": "Apple steady", "url": "https://example.com/2",
         "source": "cnbc_top", "published": "Mon, 17 Feb 2026",
         "matched_symbols": ["AAPL"], "headline_sentiment": "neutral"},
        {"title": "AMD and Nvidia compete", "url": "https://example.com/3",
         "source": "yahoo", "published": "Mon, 17 Feb 2026",
         "matched_symbols": ["AMD", "NVDA"],
         "headline_sentiment": "bullish"},
    ],
    "errors": [],
}

MOCK_BABYPIPS_DATA = {
    "fetched": True,
    "fetch_date": "2026-02-16",
    "pairs_mentioned": ["EURUSD", "GBPJPY", "USDJPY"],
    "currency_strength": {
        "strongest": "USD", "weakest": "JPY",
        "detail": {"USD": 3, "JPY": -2, "EUR": 1},
    },
    "economic_events": ["BOE", "GDP", "CPI"],
    "key_headlines": ["The yen starts the week as the worst performer."],
    "error": None,
}

MOCK_HN_DATA = {
    "stories_checked": 30,
    "stories_matched": 2,
    "matched": [
        {"title": "Nvidia announces new GPU architecture",
         "url": "https://example.com/hn1", "hn_score": 450,
         "comments": 200, "matched_symbols": ["NVDA"],
         "relevance_keywords": ["GPU", "NVIDIA"]},
        {"title": "OpenAI raises $10B for AI infrastructure",
         "url": "https://example.com/hn2", "hn_score": 300,
         "comments": 150, "matched_symbols": [],
         "relevance_keywords": ["AI", "OpenAI"]},
    ],
    "error": None,
}


# -- Tests ---------------------------------------------------------------

class TestMatchSymbols(unittest.TestCase):
    def test_matches_ticker_in_headline(self):
        result = match_symbols("NVDA beats earnings", MOCK_SYMBOLS)
        self.assertIn("NVDA", result)

    def test_matches_company_name(self):
        result = match_symbols(
            "Nvidia reports record revenue", MOCK_SYMBOLS)
        self.assertIn("NVDA", result)

    def test_matches_forex_pair_slash(self):
        result = match_symbols(
            "EUR/USD rises to 1.0950", MOCK_SYMBOLS)
        self.assertIn("EURUSD", result)

    def test_matches_forex_pair_concatenated(self):
        result = match_symbols(
            "USDJPY falls on BOJ news", MOCK_SYMBOLS)
        self.assertIn("USDJPY", result)

    def test_no_false_positive_ai_lowercase(self):
        """Lowercase 'ai' in common words should NOT match AI ticker."""
        result = match_symbols(
            "The aide told lawmakers about the main issue",
            MOCK_SYMBOLS)
        self.assertNotIn("AI", result)

    def test_no_false_positive_ai_uppercase(self):
        """Bare 'AI' as tech concept should NOT match C3.ai ticker."""
        result = match_symbols(
            "AI is destroying Open Source", MOCK_SYMBOLS)
        self.assertNotIn("AI", result)

    def test_ai_ticker_c3_matches(self):
        result = match_symbols(
            "C3.ai reports quarterly revenue", MOCK_SYMBOLS)
        self.assertIn("AI", result)

    def test_arm_case_sensitive(self):
        """'arm' in lowercase context should NOT match ARM ticker."""
        result = match_symbols(
            "The army moves to new position", MOCK_SYMBOLS)
        self.assertNotIn("ARM", result)

    def test_arm_proper_matches(self):
        result = match_symbols(
            "Arm Holdings posts gains", MOCK_SYMBOLS)
        self.assertIn("ARM", result)

    def test_multiple_symbols_one_headline(self):
        result = match_symbols(
            "Apple and Nvidia lead tech rally", MOCK_SYMBOLS)
        self.assertIn("AAPL", result)
        self.assertIn("NVDA", result)

    def test_empty_text(self):
        result = match_symbols("", MOCK_SYMBOLS)
        self.assertEqual(result, [])

    def test_crypto_matches(self):
        result = match_symbols(
            "Bitcoin surges past $100K", MOCK_SYMBOLS)
        self.assertIn("BTC", result)

    def test_google_alias(self):
        result = match_symbols(
            "Google announces new AI model", MOCK_SYMBOLS)
        self.assertIn("GOOGL", result)

    def test_salesforce_alias(self):
        result = match_symbols(
            "Salesforce beats earnings expectations", MOCK_SYMBOLS)
        self.assertIn("CRM", result)


class TestHeadlineSentiment(unittest.TestCase):
    def test_bullish(self):
        self.assertEqual(
            headline_sentiment(
                "Nvidia stock surges on record earnings"),
            "bullish")

    def test_bearish(self):
        self.assertEqual(
            headline_sentiment(
                "Market crash fears as tech stocks plunge"),
            "bearish")

    def test_neutral(self):
        self.assertEqual(
            headline_sentiment(
                "Fed meeting scheduled for next week"),
            "neutral")

    def test_mixed_equal(self):
        # "rally" (1 bull) vs "fears" (1 bear) = neutral
        self.assertEqual(
            headline_sentiment(
                "Rally despite fears of change"),
            "neutral")

    def test_empty(self):
        self.assertEqual(headline_sentiment(""), "neutral")

    def test_bullish_wins(self):
        self.assertEqual(
            headline_sentiment(
                "Strong growth and momentum beat decline fears"),
            "bullish")


class TestParseRssXml(unittest.TestCase):
    def test_valid_rss(self):
        articles = parse_rss_xml(MOCK_RSS_XML)
        self.assertEqual(len(articles), 3)
        self.assertEqual(
            articles[0]["title"],
            "Nvidia stock surges on record AI chip earnings")
        self.assertEqual(articles[0]["link"], "https://example.com/1")

    def test_skips_missing_title(self):
        articles = parse_rss_xml(MOCK_RSS_XML)
        titles = [a["title"] for a in articles]
        self.assertTrue(all(t for t in titles))

    def test_empty_feed(self):
        xml = b"""<?xml version="1.0"?>
        <rss><channel><title>Empty</title></channel></rss>"""
        articles = parse_rss_xml(xml)
        self.assertEqual(articles, [])

    def test_no_channel(self):
        xml = b"""<?xml version="1.0"?><rss></rss>"""
        articles = parse_rss_xml(xml)
        self.assertEqual(articles, [])


class TestBuildSymbolMentions(unittest.TestCase):
    def test_aggregates_across_sources(self):
        mentions = build_symbol_mentions(
            MOCK_RSS_DATA, MOCK_BABYPIPS_DATA, MOCK_HN_DATA)
        self.assertEqual(mentions["NVDA"]["total_mentions"], 3)

    def test_sources_tracked(self):
        mentions = build_symbol_mentions(
            MOCK_RSS_DATA, MOCK_BABYPIPS_DATA, MOCK_HN_DATA)
        self.assertIn("rss", mentions["NVDA"]["sources"])
        self.assertIn("hackernews", mentions["NVDA"]["sources"])

    def test_net_sentiment_bullish(self):
        mentions = build_symbol_mentions(
            MOCK_RSS_DATA, MOCK_BABYPIPS_DATA, MOCK_HN_DATA)
        self.assertEqual(mentions["NVDA"]["net_sentiment"], "bullish")

    def test_babypips_pairs(self):
        mentions = build_symbol_mentions(
            MOCK_RSS_DATA, MOCK_BABYPIPS_DATA, MOCK_HN_DATA)
        self.assertIn("EURUSD", mentions)
        self.assertIn("babypips", mentions["EURUSD"]["sources"])

    def test_empty_inputs(self):
        empty = {"matched": [], "articles_matched": 0}
        empty_bp = {"fetched": False, "pairs_mentioned": []}
        empty_hn = {"matched": [], "stories_matched": 0}
        mentions = build_symbol_mentions(empty, empty_bp, empty_hn)
        self.assertEqual(mentions, {})


class TestBuildSummary(unittest.TestCase):
    def test_most_mentioned(self):
        mentions = build_symbol_mentions(
            MOCK_RSS_DATA, MOCK_BABYPIPS_DATA, MOCK_HN_DATA)
        summary = build_summary(
            MOCK_RSS_DATA, MOCK_BABYPIPS_DATA, MOCK_HN_DATA, mentions)
        self.assertEqual(summary["most_mentioned"], "NVDA")

    def test_overall_sentiment(self):
        mentions = build_symbol_mentions(
            MOCK_RSS_DATA, MOCK_BABYPIPS_DATA, MOCK_HN_DATA)
        summary = build_summary(
            MOCK_RSS_DATA, MOCK_BABYPIPS_DATA, MOCK_HN_DATA, mentions)
        # 2 bullish, 1 neutral -> bull(2) > bear(0) but not > bear+2
        self.assertEqual(summary["headline_sentiment"],
                         "Somewhat_Bullish")

    def test_empty_data(self):
        empty = {"matched": [], "feeds_succeeded": 0,
                 "articles_matched": 0}
        empty_bp = {"fetched": False, "pairs_mentioned": [],
                    "key_headlines": []}
        empty_hn = {"matched": [], "stories_matched": 0, "error": None}
        summary = build_summary(empty, empty_bp, empty_hn, {})
        self.assertEqual(summary["total_articles"], 0)
        self.assertIsNone(summary["most_mentioned"])


class TestFormatSupplementaryMarkdown(unittest.TestCase):
    def test_contains_header(self):
        data = {
            "sources": {
                "rss": MOCK_RSS_DATA,
                "babypips": MOCK_BABYPIPS_DATA,
                "hackernews": MOCK_HN_DATA,
            },
            "summary": {
                "total_articles": 6, "sources_succeeded": 3,
                "most_mentioned": "NVDA",
                "headline_sentiment": "Somewhat_Bullish",
            },
        }
        lines = format_supplementary_markdown(data)
        self.assertEqual(lines[0], "## Supplementary News")

    def test_rss_table(self):
        data = {
            "sources": {
                "rss": MOCK_RSS_DATA,
                "babypips": {"fetched": False},
                "hackernews": {"matched": []},
            },
            "summary": {
                "total_articles": 3, "sources_succeeded": 1,
                "most_mentioned": "NVDA",
                "headline_sentiment": "Bullish",
            },
        }
        text = "\n".join(format_supplementary_markdown(data))
        self.assertIn("NVDA", text)
        self.assertIn("yahoo", text)

    def test_empty_data_returns_empty(self):
        data = {
            "sources": {
                "rss": {"matched": []},
                "babypips": {"fetched": False},
                "hackernews": {"matched": []},
            },
            "summary": {},
        }
        lines = format_supplementary_markdown(data)
        self.assertEqual(lines, [])

    def test_babypips_section_rendered(self):
        data = {
            "sources": {
                "rss": {"matched": []},
                "babypips": MOCK_BABYPIPS_DATA,
                "hackernews": {"matched": []},
            },
            "summary": {
                "total_articles": 1, "sources_succeeded": 1,
                "most_mentioned": None,
                "headline_sentiment": "Neutral",
            },
        }
        text = "\n".join(format_supplementary_markdown(data))
        self.assertIn("BabyPips Daily Recap", text)
        self.assertIn("EURUSD", text)
        self.assertIn("USD", text)

    def test_hackernews_section_rendered(self):
        data = {
            "sources": {
                "rss": {"matched": []},
                "babypips": {"fetched": False},
                "hackernews": MOCK_HN_DATA,
            },
            "summary": {
                "total_articles": 2, "sources_succeeded": 1,
                "most_mentioned": "NVDA",
                "headline_sentiment": "Neutral",
            },
        }
        text = "\n".join(format_supplementary_markdown(data))
        self.assertIn("Hacker News", text)
        self.assertIn("450 pts", text)

    def test_pipe_in_title_escaped(self):
        data = {
            "sources": {
                "rss": {
                    "feeds_attempted": 1, "feeds_succeeded": 1,
                    "articles_found": 1, "articles_matched": 1,
                    "matched": [{
                        "title": "Apple | Nvidia | AMD lead rally",
                        "url": "https://example.com",
                        "source": "yahoo",
                        "published": "",
                        "matched_symbols": ["AAPL"],
                        "headline_sentiment": "bullish",
                    }],
                    "errors": [],
                },
                "babypips": {"fetched": False},
                "hackernews": {"matched": []},
            },
            "summary": {
                "total_articles": 1, "sources_succeeded": 1,
                "most_mentioned": "AAPL",
                "headline_sentiment": "Bullish",
            },
        }
        text = "\n".join(format_supplementary_markdown(data))
        # Pipes in title should be escaped to not break table
        self.assertIn("\\|", text)


class TestNormalizePair(unittest.TestCase):
    def test_standard_order(self):
        self.assertEqual(_normalize_pair("EUR", "USD"), "EURUSD")

    def test_reversed_order(self):
        self.assertEqual(_normalize_pair("USD", "EUR"), "EURUSD")

    def test_jpy_pairs(self):
        self.assertEqual(_normalize_pair("JPY", "USD"), "USDJPY")
        self.assertEqual(_normalize_pair("USD", "JPY"), "USDJPY")

    def test_cross_pair(self):
        self.assertEqual(_normalize_pair("JPY", "GBP"), "GBPJPY")

    def test_unknown_pair_kept_as_is(self):
        self.assertEqual(_normalize_pair("XYZ", "ABC"), "XYZABC")


class TestEscapePipe(unittest.TestCase):
    def test_escapes_pipe(self):
        self.assertEqual(
            _escape_pipe("Apple | Nvidia"), "Apple \\| Nvidia")

    def test_no_pipe(self):
        self.assertEqual(_escape_pipe("Apple beats"), "Apple beats")

    def test_empty(self):
        self.assertEqual(_escape_pipe(""), "")


class TestBuildSymbolSet(unittest.TestCase):
    def test_includes_all_classes(self):
        symbols = build_symbol_set(MOCK_WATCHLIST)
        self.assertIn("EURUSD", symbols)
        self.assertIn("AAPL", symbols)
        self.assertIn("BTC", symbols)

    def test_empty_watchlist(self):
        self.assertEqual(build_symbol_set({}), set())


class TestParseRssXmlSecurity(unittest.TestCase):
    def test_rejects_dtd_entity(self):
        xml = b"""<?xml version="1.0"?>
        <!DOCTYPE foo [<!ENTITY xxe "boom">]>
        <rss><channel><item><title>&xxe;</title></item></channel></rss>"""
        with self.assertRaises(ValueError):
            parse_rss_xml(xml)

    def test_rejects_doctype(self):
        xml = b"""<?xml version="1.0"?>
        <!DOCTYPE rss SYSTEM "http://evil.com/dtd">
        <rss><channel></channel></rss>"""
        with self.assertRaises(ValueError):
            parse_rss_xml(xml)


class TestMatchSymbolsFalsePositives(unittest.TestCase):
    def test_path_lowercase_no_match(self):
        result = match_symbols(
            "The path to lower inflation is unclear", MOCK_SYMBOLS)
        self.assertNotIn("PATH", result)

    def test_snow_lowercase_no_match(self):
        result = match_symbols(
            "Heavy snow expected in northeast", MOCK_SYMBOLS)
        self.assertNotIn("SNOW", result)

    def test_dell_lowercase_no_match(self):
        result = match_symbols(
            "A dell in the valley below", MOCK_SYMBOLS)
        self.assertNotIn("DELL", result)

    def test_path_uppercase_matches(self):
        result = match_symbols("PATH stock drops 5%", MOCK_SYMBOLS)
        self.assertIn("PATH", result)

    def test_uipath_alias_matches(self):
        result = match_symbols(
            "UiPath reports quarterly earnings", MOCK_SYMBOLS)
        self.assertIn("PATH", result)

    def test_snowflake_alias_matches(self):
        result = match_symbols(
            "Snowflake data cloud revenue up 30%", MOCK_SYMBOLS)
        self.assertIn("SNOW", result)


if __name__ == "__main__":
    unittest.main()
