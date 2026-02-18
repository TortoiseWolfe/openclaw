#!/usr/bin/env python3
"""BabyPips forex education lesson fetcher.

Reads curriculum-progress.md to find the next pending lesson, fetches the
BabyPips page, extracts text content, writes a summary, and updates progress.

Designed to be called via a single `exec` tool call from the cron job.
"""

import os
import re
import sys
from datetime import date
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from content_security import detect_suspicious, wrap_external

# ── Paths (inside Docker container) ──────────────────────────────────

EDU_DIR = "/home/node/repos/Trading/education"
CURRICULUM = os.path.join(EDU_DIR, "curriculum-progress.md")
SUMMARIES_DIR = os.path.join(EDU_DIR, "article-summaries")


# ── HTML content extractor ───────────────────────────────────────────

class ContentExtractor(HTMLParser):
    """Extract text content from HTML, targeting article/main content."""

    SKIP_TAGS = {"script", "style", "nav", "footer", "header", "aside", "select"}
    SKIP_CLASSES = {"dropdown", "translate", "lang", "sidebar", "menu"}

    def __init__(self):
        super().__init__()
        self._text = []
        self._skip_stack = []  # tags that entered skip mode
        self._article_tag = None  # tag that opened article mode
        self._article_depth = 0   # nesting depth for same-tag children
        self._in_article = False
        self._article_text = []

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        classes = attr_dict.get("class", "")
        if tag in self.SKIP_TAGS or any(k in classes for k in self.SKIP_CLASSES):
            self._skip_stack.append(tag)
        if not self._in_article:
            if tag == "article" or (tag == "div" and "article" in classes):
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

    def get_content(self, max_words=2000):
        """Return extracted text, preferring article content."""
        source = self._article_text if self._article_text else self._text
        raw = " ".join(source)
        raw = _clean_babypips(raw)
        words = raw.split()
        return " ".join(words[:max_words])


def _clean_babypips(text):
    """Remove known BabyPips noise from extracted text."""
    # Strip language selector blocks (may appear multiple times)
    text = re.sub(
        r"(Translate\s+)?(English\s+)?العربية.*?繁體中文\s*\(Traditional Chinese\)\s*",
        "", text,
    )
    # Strip breadcrumb nav (School of Pipsology > Level > Section > Lesson)
    text = re.sub(
        r"School of Pipsology\s+(Preschool|Kindergarten|Elementary|Middle School"
        r"|High School|College|Graduate)\s+[^.!?]{0,100}?\s+(?=\w)",
        "", text, count=1,
    )
    # Strip "Translate" followed by language names without Arabic
    text = re.sub(r"Translate\s+\w+.*?Chinese\)\s*", "", text)
    # Strip trailing "Next Lesson ..." and "Previous Lesson ..."
    text = re.sub(r"\s*(Next|Previous) Lesson\s+.*$", "", text)
    # Strip "Partner Center" nav text
    text = re.sub(r"\bPartner Center\b", "", text)
    # Collapse multiple spaces
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


# ── Curriculum parser ────────────────────────────────────────────────

def parse_curriculum(path):
    """Parse curriculum-progress.md and return list of lesson dicts."""
    with open(path) as f:
        content = f.read()

    lessons = []
    current_level = "Unknown"
    # Match level headings like "## Kindergarten Lessons"
    heading_pattern = re.compile(r"^## (.+?) Lessons", re.MULTILINE)
    # Match table rows: | # | Section | Lesson | URL | Status | Date |
    row_pattern = re.compile(
        r"^\|\s*(\d+)\s*\|"       # lesson number
        r"\s*([^|]*?)\s*\|"       # section
        r"\s*([^|]*?)\s*\|"       # lesson name
        r"\s*(https?://[^|]*?)\s*\|"  # URL
        r"\s*(\w[\w-]*)\s*\|"     # status
        r"\s*([^|]*?)\s*\|",      # date
        re.MULTILINE,
    )

    for line in content.splitlines():
        hm = heading_pattern.match(line)
        if hm:
            current_level = hm.group(1).strip()
        rm = row_pattern.match(line)
        if rm:
            lessons.append({
                "num": int(rm.group(1)),
                "section": rm.group(2).strip(),
                "lesson": rm.group(3).strip(),
                "url": rm.group(4).strip(),
                "status": rm.group(5).strip(),
                "date": rm.group(6).strip(),
                "level": current_level,
            })

    return lessons


def find_next_pending(lessons):
    """Return the first pending lesson, or None."""
    for lesson in lessons:
        if lesson["status"] == "pending":
            return lesson
    return None


# ── Page fetcher ─────────────────────────────────────────────────────

def fetch_page(url):
    """Fetch a web page and return its HTML content."""
    req = Request(url, headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urlopen(req, timeout=30) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset)


def extract_content(html):
    """Extract text content from HTML."""
    parser = ContentExtractor()
    parser.feed(html)
    return parser.get_content(max_words=2000)


# ── Summary writer ───────────────────────────────────────────────────

def slugify(text):
    """Convert text to URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text.strip("-")


def write_summary(lesson, content, today):
    """Write lesson summary to article-summaries directory."""
    os.makedirs(SUMMARIES_DIR, exist_ok=True)
    slug = slugify(lesson["lesson"])
    filename = f"{slug}-{today.isoformat()}.md"
    path = os.path.join(SUMMARIES_DIR, filename)

    lines = [
        f"# {lesson['lesson']}",
        "",
        f"**Source**: {lesson['url']}",
        f"**Date**: {today.isoformat()}",
        f"**Level**: {lesson.get('level', 'Unknown')}",
        f"**Section**: {lesson['section']}",
        "",
        "## Key Concepts",
        "",
        content,
        "",
    ]

    with open(path, "w") as f:
        f.write("\n".join(lines))

    return path


# ── Curriculum updater ───────────────────────────────────────────────

def update_curriculum(lesson_num, new_status, today):
    """Update a lesson's status in curriculum-progress.md."""
    with open(CURRICULUM) as f:
        content = f.read()

    # Match the specific lesson row by number at the start
    pattern = re.compile(
        r"^(\|\s*" + str(lesson_num) + r"\s*\|"  # lesson number
        r"[^|]*\|"           # section
        r"[^|]*\|"           # lesson name
        r"[^|]*\|)"          # URL
        r"\s*\w[\w-]*\s*\|"  # old status
        r"\s*[^|]*\s*\|",    # old date
        re.MULTILINE,
    )

    def replacer(m):
        prefix = m.group(1)
        return f"{prefix} {new_status} | {today.isoformat()} |"

    new_content = pattern.sub(replacer, content, count=1)

    with open(CURRICULUM, "w") as f:
        f.write(new_content)


# ── Main ─────────────────────────────────────────────────────────────

def main():
    today = date.today()

    # Parse curriculum
    try:
        lessons = parse_curriculum(CURRICULUM)
    except FileNotFoundError:
        print("ERROR: curriculum-progress.md not found", file=sys.stderr)
        sys.exit(1)

    if not lessons:
        print("ERROR: No lessons found in curriculum-progress.md", file=sys.stderr)
        sys.exit(1)

    # Find next pending lesson
    lesson = find_next_pending(lessons)
    if lesson is None:
        print("All lessons completed! Time to add the next level.")
        return

    print(f"Lesson #{lesson['num']}: {lesson['lesson']}")
    print(f"Section: {lesson['section']}")
    print(f"URL: {lesson['url']}")

    # Fetch and extract content
    try:
        html = fetch_page(lesson["url"])
        content = extract_content(html)

        if len(content.split()) < 50:
            print("\nWARNING: Extracted very little content (may be JS-rendered)",
                  file=sys.stderr)
            print(f"\nFetch returned minimal content. Study manually at: {lesson['url']}")
            update_curriculum(lesson["num"], "fetch-failed", today)
            return

        # Write summary
        summary_path = write_summary(lesson, content, today)
        print(f"\nSummary saved: {summary_path}")
        print(f"Content length: {len(content.split())} words")

        # Update curriculum
        update_curriculum(lesson["num"], "done", today)
        print(f"Curriculum updated: lesson #{lesson['num']} marked done")

        # Check fetched content for suspicious patterns
        flags = detect_suspicious(content)
        if flags:
            print(f"[security] Suspicious patterns in web content: {flags}",
                  file=sys.stderr)

        # Print first 200 words as preview, wrapped as untrusted
        preview_words = content.split()[:200]
        preview = " ".join(preview_words) + "..."
        print(f"\n--- Preview ---\n{wrap_external(preview, source='web', sender=lesson['url'])}")

    except (HTTPError, URLError) as e:
        print(f"\nFetch failed: {e}", file=sys.stderr)
        print(f"Could not fetch lesson page. Study manually at: {lesson['url']}")
        update_curriculum(lesson["num"], "fetch-failed", today)

    except Exception as e:
        print(f"\nUnexpected error: {e}", file=sys.stderr)
        print(f"Study manually at: {lesson['url']}")
        update_curriculum(lesson["num"], "fetch-failed", today)


if __name__ == "__main__":
    main()
