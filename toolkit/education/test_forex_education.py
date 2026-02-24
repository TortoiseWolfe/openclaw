#!/usr/bin/env python3
"""Tests for forex_education.py — pure functions and ContentExtractor."""

import unittest

from forex_education import (
    slugify,
    _clean_babypips,
    ContentExtractor,
    parse_curriculum,
    find_next_pending,
)


class TestSlugify(unittest.TestCase):
    def test_simple_text(self):
        self.assertEqual(slugify("Hello World"), "hello-world")

    def test_strips_special_characters(self):
        self.assertEqual(slugify("What is Forex?"), "what-is-forex")

    def test_collapses_spaces_and_underscores(self):
        self.assertEqual(slugify("foo   bar__baz"), "foo-bar-baz")

    def test_strips_leading_trailing_hyphens(self):
        self.assertEqual(slugify("  --hello--  "), "hello")

    def test_empty_string(self):
        self.assertEqual(slugify(""), "")


class TestCleanBabypips(unittest.TestCase):
    def test_removes_language_selector(self):
        text = "Some text Translate English العربية blah 繁體中文 (Traditional Chinese) more text"
        result = _clean_babypips(text)
        self.assertNotIn("العربية", result)
        self.assertIn("more text", result)

    def test_removes_next_lesson(self):
        text = "Lesson content here. Next Lesson How to Trade Forex"
        result = _clean_babypips(text)
        self.assertNotIn("Next Lesson", result)
        self.assertIn("Lesson content here.", result)

    def test_removes_previous_lesson(self):
        text = "Lesson content. Previous Lesson Introduction to Forex"
        result = _clean_babypips(text)
        self.assertNotIn("Previous Lesson", result)

    def test_removes_partner_center(self):
        text = "Some text Partner Center more text"
        result = _clean_babypips(text)
        self.assertNotIn("Partner Center", result)

    def test_collapses_whitespace(self):
        text = "Hello    world     test"
        result = _clean_babypips(text)
        self.assertEqual(result, "Hello world test")


class TestContentExtractor(unittest.TestCase):
    def test_extracts_plain_text(self):
        parser = ContentExtractor()
        parser.feed("<p>Hello world</p>")
        self.assertIn("Hello world", parser.get_content())

    def test_skips_script_tags(self):
        parser = ContentExtractor()
        parser.feed("<script>var x = 1;</script><p>Visible</p>")
        content = parser.get_content()
        self.assertNotIn("var x", content)
        self.assertIn("Visible", content)

    def test_skips_style_tags(self):
        parser = ContentExtractor()
        parser.feed("<style>.foo { color: red; }</style><p>Visible</p>")
        content = parser.get_content()
        self.assertNotIn("color", content)

    def test_prefers_article_content(self):
        parser = ContentExtractor()
        parser.feed("<div>Outside</div><article><p>Inside article</p></article>")
        content = parser.get_content()
        self.assertIn("Inside article", content)

    def test_max_words_limit(self):
        parser = ContentExtractor()
        long_text = " ".join(["word"] * 3000)
        parser.feed(f"<article><p>{long_text}</p></article>")
        content = parser.get_content(max_words=100)
        self.assertLessEqual(len(content.split()), 100)


class TestParseCurriculum(unittest.TestCase):
    def test_parses_table_rows(self):
        md = (
            "| # | Section | Lesson | URL | Status | Date |\n"
            "|---|---------|--------|-----|--------|------|\n"
            "| 1 | Preschool | What is Forex | https://example.com/1 | done | 2026-01-15 |\n"
            "| 2 | Preschool | Market Players | https://example.com/2 | pending | |\n"
        )
        import tempfile, os
        fd, path = tempfile.mkstemp(suffix=".md")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(md)
            lessons = parse_curriculum(path)
            self.assertEqual(len(lessons), 2)
            self.assertEqual(lessons[0]["num"], 1)
            self.assertEqual(lessons[0]["status"], "done")
            self.assertEqual(lessons[1]["status"], "pending")
            self.assertEqual(lessons[1]["url"], "https://example.com/2")
        finally:
            os.unlink(path)

    def test_empty_file_returns_empty(self):
        import tempfile, os
        fd, path = tempfile.mkstemp(suffix=".md")
        try:
            os.close(fd)
            lessons = parse_curriculum(path)
            self.assertEqual(lessons, [])
        finally:
            os.unlink(path)


class TestFindNextPending(unittest.TestCase):
    def test_returns_first_pending(self):
        lessons = [
            {"num": 1, "status": "done"},
            {"num": 2, "status": "pending"},
            {"num": 3, "status": "pending"},
        ]
        result = find_next_pending(lessons)
        self.assertEqual(result["num"], 2)

    def test_returns_none_when_all_done(self):
        lessons = [
            {"num": 1, "status": "done"},
            {"num": 2, "status": "done"},
        ]
        self.assertIsNone(find_next_pending(lessons))

    def test_empty_list_returns_none(self):
        self.assertIsNone(find_next_pending([]))


if __name__ == "__main__":
    unittest.main()
