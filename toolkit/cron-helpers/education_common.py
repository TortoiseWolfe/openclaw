"""Shared utilities for education scrapers.

Extracted from forex_education.py, investopedia_education.py,
tradingview_education.py to eliminate triplication (CODE-REVIEW #24-26).
"""

import re
import sys
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

_robots_cache = {}
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _check_robots(url):
    """Check robots.txt for the given URL. Returns True if allowed."""
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin not in _robots_cache:
        rp = RobotFileParser()
        rp.set_url(f"{origin}/robots.txt")
        try:
            rp.read()
        except Exception:
            # If we can't read robots.txt, allow (fail-open for availability)
            _robots_cache[origin] = None
            return True
        _robots_cache[origin] = rp
    rp = _robots_cache[origin]
    if rp is None:
        return True
    return rp.can_fetch(_USER_AGENT, url)


def fetch_page(url, respect_robots=True):
    """Fetch a web page and return its HTML content."""
    if respect_robots and not _check_robots(url):
        print(f"  SKIP (robots.txt disallows): {url}", file=sys.stderr)
        raise RuntimeError(f"robots.txt disallows fetching {url}")
    req = Request(url, headers={
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urlopen(req, timeout=30) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset)


def slugify(text):
    """Convert text to URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text.strip("-")


class ContentExtractor(HTMLParser):
    """Extract text content from HTML, targeting article/main content.

    Subclass or configure via constructor args for site-specific behavior:
        skip_classes: set of CSS class substrings that trigger skip mode
        article_classes: set of CSS class substrings that trigger article mode
        article_ids: set of element IDs that trigger article mode
    """

    SKIP_TAGS = {"script", "style", "nav", "footer", "header", "aside",
                 "select", "form", "button", "svg"}

    def __init__(self, skip_classes=None, article_classes=None,
                 article_ids=None):
        super().__init__()
        self._text = []
        self._skip_stack = []
        self._article_tag = None
        self._article_depth = 0
        self._in_article = False
        self._article_text = []
        self._skip_classes = skip_classes or set()
        self._article_classes = article_classes or {"article"}
        self._article_ids = article_ids or set()

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        classes = attr_dict.get("class", "")
        elem_id = attr_dict.get("id", "")
        if tag in self.SKIP_TAGS or any(k in classes for k in self._skip_classes):
            self._skip_stack.append(tag)
        if not self._in_article:
            if (tag == "article" or
                (tag == "div" and (
                    any(k in classes for k in self._article_classes) or
                    elem_id in self._article_ids))):
                self._in_article = True
                self._article_tag = tag
                self._article_depth = 1
        elif tag == self._article_tag:
            self._article_depth += 1

    def handle_endtag(self, tag):
        if self._skip_stack and self._skip_stack[-1] == tag:
            self._skip_stack.pop()
        if self._in_article and tag == self._article_tag:
            self._article_depth -= 1
            if self._article_depth <= 0:
                self._in_article = False
                self._article_tag = None

    def handle_data(self, data):
        if self._skip_stack:
            return
        text = data.strip()
        if not text:
            return
        if self._in_article:
            self._article_text.append(text)
        self._text.append(text)

    def get_content(self, max_words=2000, post_process=None):
        """Return extracted text, preferring article content.

        post_process: optional callable to clean text before word-limiting.
        """
        source = self._article_text if self._article_text else self._text
        raw = " ".join(source)
        if post_process:
            raw = post_process(raw)
        else:
            raw = re.sub(r"\s{2,}", " ", raw).strip()
        words = raw.split()
        return " ".join(words[:max_words])
