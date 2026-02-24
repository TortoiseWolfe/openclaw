#!/usr/bin/env python3
"""
Pick random search terms from term-performance.md.

Reads a pipe-delimited markdown table with columns:
  Term | Searches | Jobs Found | Passed Filter | Avg Score | Best Score | Last Searched | Status

Randomly selects N terms, prioritizing by status (hot > untested > active > cold).

Usage:
  python3 pick_search_terms.py /path/to/term-performance.md
  python3 pick_search_terms.py /path/to/term-performance.md --count 5
  python3 pick_search_terms.py /path/to/term-performance.md --count 3 --exclude "React developer,Node.js"
"""

import random
import sys
from pathlib import Path


def parse_table(text: str) -> list[dict]:
    """Parse markdown pipe table into list of row dicts."""
    rows = []
    headers = None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if headers is None:
            headers = [h.lower().replace(' ', '_') for h in cells]
            continue
        # Skip separator row
        if all(set(c) <= {'-', ':', ' '} for c in cells):
            continue
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))
    return rows


def pick_terms(rows: list[dict], count: int, exclude: set[str]) -> list[str]:
    """Pick N terms weighted by status priority."""
    # Filter out excluded terms
    available = [r for r in rows if r.get('term', '') not in exclude]

    # Group by priority
    priority = {'hot': 3, 'untested': 2, 'active': 1, 'cold': 0}
    weighted = []
    for row in available:
        status = row.get('status', 'active').strip().lower()
        weight = priority.get(status, 1)
        # Weight determines how many times the term appears in the pool
        weighted.extend([row['term']] * max(weight, 1))

    random.shuffle(weighted)

    # Deduplicate while preserving shuffled order
    seen = set()
    picked = []
    for term in weighted:
        if term not in seen:
            seen.add(term)
            picked.append(term)
        if len(picked) >= count:
            break

    return picked


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 pick_search_terms.py <term-performance.md> [--count N] [--exclude term1,term2]")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    count = 3
    exclude = set()

    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == '--count' and i + 1 < len(args):
            count = int(args[i + 1])
            i += 2
        elif args[i] == '--exclude' and i + 1 < len(args):
            exclude = {t.strip() for t in args[i + 1].split(',')}
            i += 2
        else:
            i += 1

    text = path.read_text()
    rows = parse_table(text)

    if not rows:
        print("No terms found in table.", file=sys.stderr)
        sys.exit(1)

    picked = pick_terms(rows, count, exclude)
    for term in picked:
        print(term)


if __name__ == '__main__':
    main()
