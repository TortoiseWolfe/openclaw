#!/usr/bin/env python3
"""
Extract company names from tracker.md where status matches a filter.

Reads a pipe-delimited markdown table with columns:
  Date | Company | Role | Score | Source | Status | URL | Resume | Cover Letter | Notes

Usage:
  python3 extract_applied_companies.py /path/to/tracker.md
  python3 extract_applied_companies.py /path/to/tracker.md --status applied
  python3 extract_applied_companies.py /path/to/tracker.md --status "applied,ready"
"""

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
        if all(set(c) <= {'-', ':', ' '} for c in cells):
            continue
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))
    return rows


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 extract_applied_companies.py <tracker.md> [--status applied,ready]")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    statuses = {'applied'}
    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == '--status' and i + 1 < len(args):
            statuses = {s.strip().lower() for s in args[i + 1].split(',')}
            i += 2
        else:
            i += 1

    text = path.read_text()
    rows = parse_table(text)

    for row in rows:
        if row.get('status', '').strip().lower() in statuses:
            company = row.get('company', '').strip()
            if company and company != '--':
                print(company)


if __name__ == '__main__':
    main()
