#!/usr/bin/env python3
"""Tests for spoketowork_rotation.py"""

import unittest

from spoketowork_rotation import INDUSTRIES


class TestSpokeToWorkRotation(unittest.TestCase):
    def test_industries_has_six_entries(self):
        self.assertEqual(len(INDUSTRIES), 6)

    def test_all_industries_mention_cleveland_tn(self):
        for industry in INDUSTRIES:
            self.assertIn("Cleveland TN", industry)

    def test_rotation_cycles_through_all(self):
        seen = set()
        for week in range(1, 7):
            seen.add(INDUSTRIES[week % len(INDUSTRIES)])
        self.assertEqual(len(seen), 6)

    def test_week_modulus_wraps_correctly(self):
        # Week 6 and week 12 should map to same industry
        self.assertEqual(
            INDUSTRIES[6 % len(INDUSTRIES)],
            INDUSTRIES[12 % len(INDUSTRIES)],
        )


if __name__ == "__main__":
    unittest.main()
