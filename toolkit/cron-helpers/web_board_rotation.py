#!/usr/bin/env python3
"""
Output today's job board based on day-of-week rotation.

Mon=Indeed, Tue=Glassdoor, Wed=Google Jobs, Thu=RemoteOK, Fri=WeWorkRemotely, Sat=AngelList

Usage:
  python3 web_board_rotation.py
"""

from datetime import datetime, timezone


ROTATION = {
    0: "Indeed",         # Monday
    1: "Glassdoor",      # Tuesday
    2: "Google Jobs",    # Wednesday
    3: "RemoteOK",       # Thursday
    4: "WeWorkRemotely", # Friday
    5: "AngelList",      # Saturday
    6: "Indeed",         # Sunday (fallback)
}


def main():
    weekday = datetime.now(timezone.utc).weekday()
    print(ROTATION[weekday])


if __name__ == '__main__':
    main()
