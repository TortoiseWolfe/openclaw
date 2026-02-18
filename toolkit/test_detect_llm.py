#!/usr/bin/env python3
"""
Unit tests for detect_llm.py
"""

import unittest
from detect_llm import detect_llm_signals, count_contractions


class TestDetectLLMSignals(unittest.TestCase):
    """Test the LLM detection function."""

    def test_pass_verdict(self):
        """Human-sounding text should pass."""
        human_text = """
        Model A kept asking for permission before each step. I had to nudge it along
        constantly. The pages are fat - employees/page.tsx weighing in at 429 lines.
        One thing I noticed was the auth flow worked on first try.
        """
        result = detect_llm_signals(human_text)
        self.assertEqual(result['verdict'], "PASS")
        self.assertLessEqual(result['signal_count'], 2)

    def test_flag_verdict(self):
        """Moderately formal text should flag."""
        formal_text = """
        I would recommend that the expert provide more detailed explanations.
        It is worth noting that the implementation demonstrates adequate adherence.
        The model appears to handle the task somewhat effectively.
        """
        result = detect_llm_signals(formal_text)
        self.assertIn(result['verdict'], ["FLAG", "MAJOR FLAG"])
        self.assertGreaterEqual(result['signal_count'], 3)

    def test_major_flag_verdict(self):
        """Very formal text should major flag."""
        llm_text = """
        I would recommend implementing comprehensive error handling utilizing
        established patterns. Furthermore, it is suggested that the expert
        demonstrates proficiency in the relevant technologies. The implementation
        appears to be somewhat robust and relatively well-structured. Moreover,
        the solution is commendable and noteworthy.
        """
        result = detect_llm_signals(llm_text)
        self.assertEqual(result['verdict'], "MAJOR FLAG")
        self.assertGreaterEqual(result['signal_count'], 5)

    def test_formal_phrases_detected(self):
        """Should detect formal phrases."""
        text = "I would recommend using this approach."
        result = detect_llm_signals(text)
        categories = [m[0] for m in result['matches']]
        self.assertIn('formal_phrase', categories)

    def test_hedging_detected(self):
        """Should detect hedging language."""
        text = "This appears to be working somewhat correctly."
        result = detect_llm_signals(text)
        categories = [m[0] for m in result['matches']]
        self.assertIn('hedging', categories)

    def test_generic_praise_detected(self):
        """Should detect generic praise."""
        text = "Excellent work on this comprehensive implementation."
        result = detect_llm_signals(text)
        categories = [m[0] for m in result['matches']]
        self.assertIn('generic_praise', categories)


class TestCountContractions(unittest.TestCase):
    """Test contraction counting."""

    def test_no_contractions(self):
        """Text with no contractions."""
        text = "I did not think it would not work."
        expanded, contracted = count_contractions(text)
        self.assertEqual(expanded, 2)  # "did not", "would not"
        self.assertEqual(contracted, 0)

    def test_all_contractions(self):
        """Text with contractions."""
        text = "I didn't think it wouldn't work."
        expanded, contracted = count_contractions(text)
        self.assertEqual(expanded, 0)
        self.assertEqual(contracted, 2)  # "didn't", "wouldn't"

    def test_mixed(self):
        """Text with both."""
        text = "I didn't think it would not work."
        expanded, contracted = count_contractions(text)
        self.assertEqual(expanded, 1)  # "would not"
        self.assertEqual(contracted, 1)  # "didn't"


if __name__ == '__main__':
    unittest.main()
