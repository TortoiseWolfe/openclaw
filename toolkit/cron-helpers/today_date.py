#!/usr/bin/env python3
"""
Output today's date in YYYY-MM-DD format.

Usage:
  python3 today_date.py
  python3 today_date.py --format "%B %d, %Y"
"""

import sys
from datetime import datetime, timezone


def main():
    fmt = "%Y-%m-%d"
    if len(sys.argv) > 1 and sys.argv[1] == '--format' and len(sys.argv) > 2:
        fmt = sys.argv[2]

    print(datetime.now(timezone.utc).strftime(fmt))


if __name__ == '__main__':
    main()
