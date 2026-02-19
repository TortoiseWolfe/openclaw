#!/usr/bin/env python3
"""Tests for pick_search_terms.py"""

import random
import unittest

from pick_search_terms import parse_table, pick_terms

SAMPLE_TABLE = """\
| Term | Searches | Jobs Found | Passed Filter | Avg Score | Best Score | Last Searched | Status |
|------|----------|------------|---------------|-----------|------------|---------------|--------|
| React developer | 5 | 12 | 8 | 72 | 90 | 2026-01-10 | hot |
| Node.js engineer | 3 | 6 | 4 | 65 | 85 | 2026-01-09 | active |
| Python backend | 0 | 0 | 0 | 0 | 0 | -- | untested |
| Java developer | 10 | 2 | 0 | 30 | 40 | 2026-01-08 | cold |
"""


class TestParseTable(unittest.TestCase):
    def test_parses_standard_markdown_table(self):
        rows = parse_table(SAMPLE_TABLE)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["term"], "React developer")
        self.assertEqual(rows[0]["status"], "hot")

    def test_skips_separator_row(self):
        rows = parse_table(SAMPLE_TABLE)
        terms = [r["term"] for r in rows]
        self.assertNotIn("------", str(terms))

    def test_normalizes_headers_to_lowercase_underscored(self):
        rows = parse_table(SAMPLE_TABLE)
        self.assertIn("jobs_found", rows[0])
        self.assertIn("avg_score", rows[0])
        self.assertIn("last_searched", rows[0])

    def test_returns_empty_for_no_table(self):
        rows = parse_table("No table here, just text.")
        self.assertEqual(rows, [])

    def test_handles_extra_whitespace_in_cells(self):
        table = "| Term | Status |\n|---|---|\n|  spaced term  |  hot  |"
        rows = parse_table(table)
        self.assertEqual(rows[0]["term"], "spaced term")
        self.assertEqual(rows[0]["status"], "hot")

    def test_skips_lines_without_pipes(self):
        table = "# Header\n\n| Term | Status |\n|---|---|\n| test | active |\n\nFooter"
        rows = parse_table(table)
        self.assertEqual(len(rows), 1)


class TestPickTerms(unittest.TestCase):
    def setUp(self):
        self.rows = parse_table(SAMPLE_TABLE)

    def test_picks_up_to_count_terms(self):
        random.seed(42)
        picked = pick_terms(self.rows, 2, set())
        self.assertEqual(len(picked), 2)

    def test_excludes_specified_terms(self):
        random.seed(42)
        picked = pick_terms(self.rows, 10, {"React developer"})
        self.assertNotIn("React developer", picked)

    def test_returns_empty_when_all_excluded(self):
        all_terms = {r["term"] for r in self.rows}
        picked = pick_terms(self.rows, 3, all_terms)
        self.assertEqual(picked, [])

    def test_deduplicates_results(self):
        random.seed(42)
        picked = pick_terms(self.rows, 10, set())
        self.assertEqual(len(picked), len(set(picked)))


if __name__ == "__main__":
    unittest.main()
