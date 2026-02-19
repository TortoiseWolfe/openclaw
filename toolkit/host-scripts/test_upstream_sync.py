#!/usr/bin/env python3
"""Tests for upstream_sync.py — pure functions only, no network or git calls."""

import json
import unittest
from unittest.mock import patch

# Add parent dir to path so we can import the module
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from upstream_sync import (
    parse_version_date,
    version_newer,
    days_between,
    scan_keywords,
    classify_urgency,
    fetch_releases_since,
    build_status,
    format_summary,
    SECURITY_KEYWORDS,
    BREAKING_KEYWORDS,
)


class TestParseVersionDate(unittest.TestCase):
    def test_standard(self):
        self.assertEqual(parse_version_date("2026.1.29"), (2026, 1, 29))

    def test_with_v_prefix(self):
        self.assertEqual(parse_version_date("v2026.2.17"), (2026, 2, 17))

    def test_two_digit_month_day(self):
        self.assertEqual(parse_version_date("2026.12.31"), (2026, 12, 31))

    def test_with_suffix(self):
        self.assertEqual(parse_version_date("2026.2.15-beta.1"), (2026, 2, 15))

    def test_invalid(self):
        self.assertIsNone(parse_version_date("not-a-version"))

    def test_empty(self):
        self.assertIsNone(parse_version_date(""))

    def test_semver_rejected(self):
        # Regular semver doesn't match (year must be 4 digits)
        self.assertIsNone(parse_version_date("1.2.3"))


class TestVersionNewer(unittest.TestCase):
    def test_newer(self):
        self.assertTrue(version_newer("2026.2.17", "2026.1.29"))

    def test_same(self):
        self.assertFalse(version_newer("2026.1.29", "2026.1.29"))

    def test_older(self):
        self.assertFalse(version_newer("2026.1.1", "2026.1.29"))

    def test_year_ahead(self):
        self.assertTrue(version_newer("2027.1.1", "2026.12.31"))

    def test_same_month_different_day(self):
        self.assertTrue(version_newer("2026.2.17", "2026.2.10"))

    def test_unparseable_different(self):
        # Fallback: different strings = "newer"
        self.assertTrue(version_newer("unknown", "2026.1.29"))

    def test_unparseable_same(self):
        self.assertFalse(version_newer("unknown", "unknown"))


class TestDaysBetween(unittest.TestCase):
    def test_known_gap(self):
        self.assertEqual(days_between("2026.2.17", "2026.1.29"), 19)

    def test_same(self):
        self.assertEqual(days_between("2026.1.29", "2026.1.29"), 0)

    def test_reversed(self):
        # abs() — order doesn't matter
        self.assertEqual(days_between("2026.1.29", "2026.2.17"), 19)

    def test_unparseable(self):
        self.assertIsNone(days_between("unknown", "2026.1.29"))


class TestScanKeywords(unittest.TestCase):
    def test_finds_security(self):
        hits = scan_keywords("Fix CVE-2026-1234 vulnerability", SECURITY_KEYWORDS)
        self.assertIn("CVE", hits)
        self.assertIn("vulnerability", hits)

    def test_case_insensitive(self):
        hits = scan_keywords("SECURITY fix for SSRF", SECURITY_KEYWORDS)
        self.assertIn("security", hits)
        self.assertIn("SSRF", hits)

    def test_no_match(self):
        self.assertEqual(scan_keywords("Added dark mode", SECURITY_KEYWORDS), [])

    def test_empty(self):
        self.assertEqual(scan_keywords("", SECURITY_KEYWORDS), [])
        self.assertEqual(scan_keywords(None, SECURITY_KEYWORDS), [])

    def test_breaking(self):
        hits = scan_keywords("BREAKING: removed legacy mode", BREAKING_KEYWORDS)
        self.assertIn("BREAKING", hits)
        self.assertIn("removed", hits)

    def test_partial_match(self):
        # "sanitiz" matches "sanitize", "sanitization", etc.
        hits = scan_keywords("Add input sanitization", SECURITY_KEYWORDS)
        self.assertIn("sanitiz", hits)


class TestClassifyUrgency(unittest.TestCase):
    def test_security_is_urgent(self):
        urgency, hits = classify_urgency("Fix CVE-2026-5678 vulnerability")
        self.assertEqual(urgency, "URGENT")
        self.assertIn("CVE", hits)

    def test_breaking_is_review(self):
        urgency, hits = classify_urgency("BREAKING: removed legacy auth")
        self.assertEqual(urgency, "REVIEW")

    def test_normal_is_info(self):
        urgency, hits = classify_urgency("Added new emoji reactions")
        self.assertEqual(urgency, "INFO")
        self.assertEqual(hits, [])

    def test_security_beats_breaking(self):
        urgency, _ = classify_urgency("BREAKING: security fix for SSRF vulnerability")
        self.assertEqual(urgency, "URGENT")

    def test_name_included(self):
        urgency, _ = classify_urgency("normal body", name="Security Patch 2026.2.10")
        self.assertEqual(urgency, "URGENT")

    def test_empty_body(self):
        urgency, hits = classify_urgency(None, "v2026.2.10")
        self.assertEqual(urgency, "INFO")


class TestBuildStatus(unittest.TestCase):
    def _make_release(self, tag, body="", name=""):
        return {
            "tag_name": tag, "body": body, "name": name,
            "published_at": "2026-02-10T00:00:00Z",
            "html_url": f"https://github.com/openclaw/openclaw/releases/tag/{tag}",
        }

    def test_up_to_date(self):
        status = build_status(
            "2026.1.29", "2026.1.29", [],
            {"branch": "", "status": "up_to_date", "conflicts": [], "message": ""},
            {"status": "not_needed", "attempted": 0, "succeeded": [], "failed": [], "branch": ""},
        )
        self.assertTrue(status["is_current"])
        self.assertEqual(status["urgency"], "OK")

    def test_behind_info(self):
        missed = [self._make_release("v2026.2.5", "New feature")]
        status = build_status(
            "2026.1.29", "2026.2.5", missed,
            {"branch": "upstream-sync/2026-02-17", "status": "clean",
             "conflicts": [], "message": "OK"},
            {"status": "not_needed", "attempted": 0, "succeeded": [], "failed": [], "branch": ""},
        )
        self.assertFalse(status["is_current"])
        self.assertEqual(status["urgency"], "INFO")
        self.assertEqual(status["releases_behind"], 1)

    def test_behind_urgent(self):
        missed = [self._make_release("v2026.2.10", "Fix CVE-2026-9999")]
        status = build_status(
            "2026.1.29", "2026.2.10", missed,
            {"branch": "upstream-sync/2026-02-17", "status": "conflicts",
             "conflicts": ["src/cron/types.ts"], "message": "1 conflict"},
            {"status": "done", "attempted": 1, "branch": "security-patch/2026-02-17",
             "succeeded": [{"hash": "abc1234", "message": "Fix CVE"}], "failed": []},
        )
        self.assertEqual(status["urgency"], "URGENT")
        self.assertIn("CVE", status["security_keywords"])
        self.assertEqual(len(status["merge"]["conflicts"]), 1)


class TestFormatSummary(unittest.TestCase):
    def test_up_to_date(self):
        status = {
            "local_version": "2026.1.29", "latest_upstream": "2026.1.29",
            "is_current": True, "urgency": "OK", "days_behind": 0,
            "releases_behind": 0, "security_keywords": [],
            "breaking_keywords": [], "merge": {}, "cherry_pick": {},
            "missed_releases": [],
        }
        output = format_summary(status)
        self.assertIn("Up to date", output)

    def test_behind_with_conflicts(self):
        status = {
            "local_version": "2026.1.29", "latest_upstream": "2026.2.17",
            "is_current": False, "urgency": "INFO", "days_behind": 19,
            "releases_behind": 5, "security_keywords": [],
            "breaking_keywords": [],
            "merge": {
                "branch": "upstream-sync/2026-02-17",
                "status": "conflicts",
                "conflicts": ["src/cron/types.ts", "extensions/twitch/config.ts"],
                "message": "2 conflicts",
            },
            "cherry_pick": {"status": "not_needed", "attempted": 0},
            "missed_releases": [
                {"version": "2026.2.17", "date": "2026-02-17",
                 "urgency": "INFO", "name": "Feature release",
                 "keywords": [], "url": ""},
            ],
        }
        output = format_summary(status)
        self.assertIn("19 days", output)
        self.assertIn("conflicts", output.lower())
        self.assertIn("src/cron/types.ts", output)


if __name__ == "__main__":
    unittest.main()
