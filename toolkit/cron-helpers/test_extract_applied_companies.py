#!/usr/bin/env python3
"""Tests for extract_applied_companies.py"""

import unittest

from extract_applied_companies import parse_table

SAMPLE_TRACKER = """\
| Date | Company | Role | Score | Source | Status | URL | Resume | Cover Letter | Notes |
|------|---------|------|-------|--------|--------|-----|--------|--------------|-------|
| 2026-01-10 | Acme Corp | React Dev | 85 | LinkedIn | applied | http://x | yes | yes | -- |
| 2026-01-11 | -- | -- | -- | -- | -- | -- | -- | -- | placeholder |
| 2026-01-12 | BigTech | Node Eng | 90 | Indeed | ready | http://y | yes | no | -- |
| 2026-01-13 | SmallCo | Python Dev | 60 | Web | rejected | http://z | yes | yes | -- |
"""


class TestParseTable(unittest.TestCase):
    def test_parses_tracker_format_table(self):
        rows = parse_table(SAMPLE_TRACKER)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["company"], "Acme Corp")

    def test_skips_separator_and_header(self):
        rows = parse_table(SAMPLE_TRACKER)
        companies = [r["company"] for r in rows]
        self.assertNotIn("Company", companies)
        self.assertNotIn("-------", str(companies))

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(parse_table(""), [])


class TestStatusFiltering(unittest.TestCase):
    """Test the filtering logic used in main() — applied directly to parsed rows."""

    def _filter(self, rows, statuses):
        result = []
        for row in rows:
            if row.get("status", "").strip().lower() in statuses:
                company = row.get("company", "").strip()
                if company and company != "--":
                    result.append(company)
        return result

    def test_filters_by_applied_status(self):
        rows = parse_table(SAMPLE_TRACKER)
        result = self._filter(rows, {"applied"})
        self.assertEqual(result, ["Acme Corp"])

    def test_filters_by_multiple_statuses(self):
        rows = parse_table(SAMPLE_TRACKER)
        result = self._filter(rows, {"applied", "ready"})
        self.assertIn("Acme Corp", result)
        self.assertIn("BigTech", result)

    def test_skips_dash_company_names(self):
        rows = parse_table(SAMPLE_TRACKER)
        # The "--" placeholder row has status "--" which won't match "applied"
        result = self._filter(rows, {"--"})
        self.assertEqual(result, [])

    def test_case_insensitive_status_match(self):
        table = "| Company | Status |\n|---|---|\n| Test | Applied |"
        rows = parse_table(table)
        result = self._filter(rows, {"applied"})
        self.assertEqual(result, ["Test"])


if __name__ == "__main__":
    unittest.main()
