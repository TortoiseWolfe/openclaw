#!/usr/bin/env python3
"""
Detect LLM-generated text patterns in feedback.

Checks for:
- Formal phrases ("I would recommend", "utilizing", "it is suggested")
- Hedging ("somewhat", "relatively", "appears to")
- No contractions ("did not" vs "didn't")
- Generic praise ("excellent work", "well-structured")
- Pronoun formality ("They" for models instead of "It")

Returns signal count and specific matches.
"""

import re
import sys
from pathlib import Path


# LLM signal patterns
FORMAL_PHRASES = [
    r'\bI would recommend\b',
    r'\bIt is (suggested|recommended|worth noting|important to note)\b',
    r'\butilizing\b',
    r'\bdemonstrates? adherence\b',
    r'\bdemonstrates? proficiency\b',
    r'\bfurthermore\b',
    r'\bmoreover\b',
    r'\bnevertheless\b',
    r'\bconsequently\b',
    r'\bthus,\b',
    r'\bhence,\b',
    r'\baccordingly\b',
    r'\bin conclusion\b',
    r'\bto summarize\b',
    r'\bit should be noted\b',
    r'\bone should consider\b',
]

HEDGING_PHRASES = [
    r'\bsomewhat\b',
    r'\brelatively\b',
    r'\bappears to\b',
    r'\bseems to indicate\b',
    r'\bseems to suggest\b',
    r'\bmay potentially\b',
    r'\bcould potentially\b',
    r'\bmight potentially\b',
    r'\bit appears that\b',
]

GENERIC_PRAISE = [
    r'\bexcellent work\b',
    r'\bwell[- ]structured\b',
    r'\bcomprehensive\b',
    r'\bcommendable\b',
    r'\bnoteworthy\b',
    r'\badmirable\b',
    r'\bexemplary\b',
    r'\bpraiseworthy\b',
    r'\bimpressive\b',
    r'\brobust implementation\b',
    r'\belegant solution\b',
]

# Contractions that humans use but LLMs often avoid
CONTRACTION_PAIRS = [
    (r"\bdid not\b", "didn't"),
    (r"\bcannot\b", "can't"),
    (r"\bwill not\b", "won't"),
    (r"\bdo not\b", "don't"),
    (r"\bdoes not\b", "doesn't"),
    (r"\bis not\b", "isn't"),
    (r"\bare not\b", "aren't"),
    (r"\bwas not\b", "wasn't"),
    (r"\bwere not\b", "weren't"),
    (r"\bwould not\b", "wouldn't"),
    (r"\bcould not\b", "couldn't"),
    (r"\bshould not\b", "shouldn't"),
    (r"\bI am\b", "I'm"),
    (r"\bI have\b", "I've"),
    (r"\bI would\b", "I'd"),
    (r"\bit is\b", "it's"),
    (r"\bthat is\b", "that's"),
]

# Formal pronoun usage (referring to tools/agents as "They" instead of "It")
FORMAL_PRONOUNS = [
    r'\b(The model|the system|the agent) they\b',
    r'\bthey (demonstrate|exhibit|display|show|complete|implement)s?\b',
]


def count_contractions(text: str) -> tuple[int, int]:
    """Count expanded forms vs contractions. Returns (expanded, contracted)."""
    expanded = 0
    contracted = 0

    for expanded_pattern, contraction in CONTRACTION_PAIRS:
        expanded += len(re.findall(expanded_pattern, text, re.IGNORECASE))
        contracted += len(re.findall(re.escape(contraction), text, re.IGNORECASE))

    return expanded, contracted


def detect_llm_signals(text: str) -> dict:
    """
    Analyze text for LLM-generated patterns.

    Returns:
    - signal_count: int (total signals detected)
    - matches: list of (category, match) tuples
    - contraction_ratio: str ("3 expanded / 1 contracted")
    - verdict: str ("PASS", "FLAG", "MAJOR FLAG")
    """
    matches = []

    # Check formal phrases
    for pattern in FORMAL_PHRASES:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            matches.append(('formal_phrase', match.group()))

    # Check hedging
    for pattern in HEDGING_PHRASES:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            matches.append(('hedging', match.group()))

    # Check generic praise
    for pattern in GENERIC_PRAISE:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            matches.append(('generic_praise', match.group()))

    # Check formal pronouns
    for pattern in FORMAL_PRONOUNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            matches.append(('formal_pronoun', match.group()))

    # Check contraction avoidance
    expanded, contracted = count_contractions(text)
    contraction_ratio = f"{expanded} expanded / {contracted} contracted"

    # Count contraction avoidance as a signal if heavy imbalance
    contraction_signal = 0
    if expanded >= 3 and contracted == 0:
        contraction_signal = 1
        matches.append(('no_contractions', f"{expanded} expanded forms, 0 contractions"))
    elif expanded >= 5 and contracted <= 1:
        contraction_signal = 1
        matches.append(('few_contractions', f"{expanded} expanded forms, only {contracted} contractions"))

    signal_count = len(matches)

    # Determine verdict
    if signal_count <= 2:
        verdict = "PASS"
    elif signal_count <= 4:
        verdict = "FLAG"
    else:
        verdict = "MAJOR FLAG"

    return {
        'signal_count': signal_count,
        'matches': matches,
        'contraction_ratio': contraction_ratio,
        'verdict': verdict,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 detect_llm.py <text_file>")
        print("       python3 detect_llm.py --stdin")
        print("\nDetects LLM-generated patterns in text.")
        print("\nVerdicts:")
        print("  PASS (0-2 signals): Reads as human-written")
        print("  FLAG (3-4 signals): Likely machine-generated, review needed")
        print("  MAJOR FLAG (5+): Strong indicator of machine-generated text")
        sys.exit(1)

    if sys.argv[1] == '--stdin':
        text = sys.stdin.read()
    else:
        path = Path(sys.argv[1])
        if not path.exists():
            print(f"File not found: {sys.argv[1]}")
            sys.exit(1)
        text = path.read_text()

    result = detect_llm_signals(text)

    print(f"\n=== LLM Detection Results ===")
    print(f"Signal count: {result['signal_count']}")
    print(f"Verdict: {result['verdict']}")
    print(f"Contraction ratio: {result['contraction_ratio']}")

    if result['matches']:
        print(f"\nMatches:")
        for category, match in result['matches']:
            print(f"  [{category}] \"{match}\"")
    else:
        print("\nNo LLM signals detected.")


if __name__ == '__main__':
    main()
