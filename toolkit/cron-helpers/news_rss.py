#!/usr/bin/env python3
"""RSS feed fetching and parsing for market news.

Fetches financial RSS feeds (Yahoo Finance, CNBC), parses XML,
matches articles to watchlist symbols.
"""

import sys
import urllib.request
import xml.etree.ElementTree as ET

from content_security import detect_suspicious, sanitize_field
from news_matching import (
    match_symbols, headline_sentiment, _HEADERS, MAX_RESPONSE_BYTES,
)

RSS_FEEDS = [
    {"name": "yahoo", "url": "https://finance.yahoo.com/news/rssindex"},
    {"name": "cnbc_top",
     "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html"},
    {"name": "cnbc_tech",
     "url": ("https://search.cnbc.com/rs/search/combinedcms/view.xml"
             "?partnerId=wrss01&id=19854910")},
]


def parse_rss_xml(xml_bytes):
    """Parse RSS 2.0 XML bytes into article dicts.

    Returns list of {title, link, published, description}.
    Raises ValueError if XML contains DTD entity definitions (XXE guard).
    """
    xml_upper = xml_bytes.upper()
    if b'<!ENTITY' in xml_upper or b'<!DOCTYPE' in xml_upper or b'SYSTEM' in xml_upper:
        raise ValueError("RSS feed contains DTD/entity definitions")
    root = ET.fromstring(xml_bytes)
    articles = []

    channel = root.find("channel")
    if channel is None:
        return articles

    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        articles.append({
            "title": sanitize_field(title, max_len=300),
            "link": (item.findtext("link") or "").strip(),
            "published": (item.findtext("pubDate") or "").strip(),
            "description": sanitize_field(
                (item.findtext("description") or "").strip(), max_len=500),
        })

    return articles


def fetch_rss(url, timeout=30):
    """Fetch and parse an RSS feed. Returns list of article dicts."""
    req = urllib.request.Request(url, headers={
        **_HEADERS,
        "Accept": "application/rss+xml, application/xml, text/xml",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        xml_bytes = resp.read(MAX_RESPONSE_BYTES)
    return parse_rss_xml(xml_bytes)


def fetch_all_rss(watchlist_symbols):
    """Fetch all RSS feeds, match articles to symbols.

    Returns dict with feeds_attempted, feeds_succeeded, articles_found,
    articles_matched, matched list, errors.
    """
    result = {
        "feeds_attempted": len(RSS_FEEDS),
        "feeds_succeeded": 0,
        "articles_found": 0,
        "articles_matched": 0,
        "matched": [],
        "errors": [],
    }

    for feed in RSS_FEEDS:
        try:
            articles = fetch_rss(feed["url"])
            result["feeds_succeeded"] += 1
            result["articles_found"] += len(articles)

            for article in articles:
                search_text = f"{article['title']} {article['description']}"
                if detect_suspicious(search_text):
                    continue
                symbols = match_symbols(search_text, watchlist_symbols)
                if symbols:
                    sentiment = headline_sentiment(search_text)
                    result["matched"].append({
                        "title": article["title"],
                        "url": article["link"],
                        "source": feed["name"],
                        "published": article["published"],
                        "matched_symbols": symbols,
                        "headline_sentiment": sentiment,
                    })

            print(f"  RSS {feed['name']}: {len(articles)} articles")

        except Exception as e:
            result["errors"].append(f"{feed['name']}: {e}")
            print(f"  RSS {feed['name']}: FAILED ({e})", file=sys.stderr)

    result["articles_matched"] = len(result["matched"])
    return result
