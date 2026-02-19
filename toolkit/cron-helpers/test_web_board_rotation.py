#!/usr/bin/env python3
"""Tests for web_board_rotation.py"""

import unittest

from web_board_rotation import ROTATION


class TestWebBoardRotation(unittest.TestCase):
    def test_monday_returns_indeed(self):
        self.assertEqual(ROTATION[0], "Indeed")

    def test_tuesday_returns_glassdoor(self):
        self.assertEqual(ROTATION[1], "Glassdoor")

    def test_all_seven_days_covered(self):
        for day in range(7):
            self.assertIn(day, ROTATION)
            self.assertIsInstance(ROTATION[day], str)
            self.assertTrue(len(ROTATION[day]) > 0)

    def test_sunday_fallback_to_indeed(self):
        self.assertEqual(ROTATION[6], "Indeed")


if __name__ == "__main__":
    unittest.main()
