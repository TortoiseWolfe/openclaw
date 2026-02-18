#!/usr/bin/env python3
"""
Shared text analysis utilities.
"""

import re


def count_words(text: str) -> int:
    """Count words in text, excluding punctuation-only tokens."""
    words = [w for w in text.split() if re.search(r'\w', w)]
    return len(words)
