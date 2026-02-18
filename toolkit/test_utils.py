#!/usr/bin/env python3
"""
Unit tests for utils.py
"""

import unittest
from utils import count_words


class TestCountWords(unittest.TestCase):
    """Test the count_words function."""

    def test_simple_sentence(self):
        """Count words in a simple sentence."""
        self.assertEqual(count_words("hello world"), 2)
        self.assertEqual(count_words("one two three four five"), 5)

    def test_empty_string(self):
        """Empty string has zero words."""
        self.assertEqual(count_words(""), 0)

    def test_whitespace_only(self):
        """Whitespace-only string has zero words."""
        self.assertEqual(count_words("   \n\t  "), 0)

    def test_punctuation_excluded(self):
        """Punctuation-only tokens are not counted."""
        self.assertEqual(count_words("hello, world!"), 2)
        self.assertEqual(count_words("--- ... !!!"), 0)

    def test_mixed_punctuation(self):
        """Words with punctuation are still counted."""
        self.assertEqual(count_words("it's working!"), 2)
        self.assertEqual(count_words("don't can't won't"), 3)

    def test_minimum_threshold(self):
        """Test against a 15-word minimum threshold."""
        short_quote = "did you test this?"
        self.assertLess(count_words(short_quote), 15)

        long_quote = "role select is a 404? I thought you were going to make it part of the sign-up process instead of a separate page?"
        self.assertGreaterEqual(count_words(long_quote), 15)


if __name__ == '__main__':
    unittest.main()
