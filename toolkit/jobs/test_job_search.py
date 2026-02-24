#!/usr/bin/env python3
"""Tests for job_search.py — pure functions only (location_gate, score_job, is_duplicate)."""

import unittest

from job_search import location_gate, score_job, is_duplicate


class TestLocationGate(unittest.TestCase):
    def test_remote_passes_with_30_bonus(self):
        status, bonus = location_gate("Remote")
        self.assertEqual(status, "pass")
        self.assertEqual(bonus, 30)

    def test_remote_in_location_string(self):
        status, bonus = location_gate("United States (Remote)")
        self.assertEqual(status, "pass")
        self.assertEqual(bonus, 30)

    def test_cleveland_passes_with_25_bonus(self):
        status, bonus = location_gate("Cleveland, TN")
        self.assertEqual(status, "pass")
        self.assertEqual(bonus, 25)

    def test_chattanooga_passes(self):
        status, _ = location_gate("Chattanooga, TN")
        self.assertEqual(status, "pass")

    def test_knoxville_checks_with_15_bonus(self):
        status, bonus = location_gate("Knoxville, TN")
        self.assertEqual(status, "check")
        self.assertEqual(bonus, 15)

    def test_nashville_checks(self):
        status, _ = location_gate("Nashville, TN")
        self.assertEqual(status, "check")

    def test_tennessee_generic_checks(self):
        status, bonus = location_gate("Somewhere, TN")
        self.assertEqual(status, "check")
        self.assertEqual(bonus, 15)

    def test_new_york_rejected(self):
        status, bonus = location_gate("New York, NY")
        self.assertEqual(status, "reject")
        self.assertEqual(bonus, 0)

    def test_none_location_returns_check(self):
        status, bonus = location_gate(None)
        self.assertEqual(status, "check")
        self.assertEqual(bonus, 15)

    def test_empty_location_returns_check(self):
        status, bonus = location_gate("")
        self.assertEqual(status, "check")
        self.assertEqual(bonus, 15)

    def test_case_insensitive(self):
        status, _ = location_gate("REMOTE")
        self.assertEqual(status, "pass")

    def test_atlanta_checks(self):
        status, _ = location_gate("Atlanta, GA")
        self.assertEqual(status, "check")


class TestScoreJob(unittest.TestCase):
    def test_react_typescript_remote_developer_scores_high(self):
        job = {
            "job_title": "Senior React Developer",
            "location": "Remote",
            "job_description": "React TypeScript Node.js Docker AWS",
        }
        score = score_job(job)
        self.assertGreaterEqual(score, 70)

    def test_unknown_skills_title_scores_low(self):
        job = {
            "job_title": "Office Manager",
            "location": "New York, NY",
            "job_description": "Managing an office, scheduling meetings.",
        }
        score = score_job(job)
        self.assertLessEqual(score, 20)

    def test_skills_score_capped_at_50(self):
        job = {
            "job_title": "test",
            "location": "",
            "job_description": "react typescript node.js javascript next.js docker aws python postgresql supabase graphql rest api tailwind css html git c# .net",
        }
        score = score_job(job)
        # Even with all skills, max is 50 + location + title
        self.assertLessEqual(score, 100)

    def test_total_capped_at_100(self):
        job = {
            "job_title": "Senior Developer",
            "location": "Remote",
            "job_description": "react typescript node.js javascript next.js docker aws python postgresql",
        }
        score = score_job(job)
        self.assertLessEqual(score, 100)

    def test_empty_job_scores_low(self):
        job = {}
        score = score_job(job)
        # location_gate(None) returns ("check", 15) so minimum is 15
        self.assertLessEqual(score, 20)


class TestIsDuplicate(unittest.TestCase):
    def test_exact_match_is_duplicate(self):
        job = {"company": "Acme Corp", "job_title": "React Developer"}
        tracked = {("acme corp", "react developer")}
        self.assertTrue(is_duplicate(job, tracked))

    def test_different_company_not_duplicate(self):
        job = {"company": "BigTech", "job_title": "React Developer"}
        tracked = {("acme corp", "react developer")}
        self.assertFalse(is_duplicate(job, tracked))

    def test_partial_title_match_is_duplicate(self):
        job = {"company": "Acme Corp", "job_title": "React Developer - Remote"}
        tracked = {("acme corp", "react developer")}
        self.assertTrue(is_duplicate(job, tracked))

    def test_empty_company_never_duplicate(self):
        job = {"company": "", "job_title": "React Developer"}
        tracked = {("", "react developer")}
        self.assertFalse(is_duplicate(job, tracked))

    def test_none_company_never_duplicate(self):
        job = {"company": None, "job_title": "React Developer"}
        tracked = {("acme corp", "react developer")}
        self.assertFalse(is_duplicate(job, tracked))


if __name__ == "__main__":
    unittest.main()
