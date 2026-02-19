#!/usr/bin/env python3
"""SpokeToWork employer search rotation.

Outputs a maps_search_places query based on ISO week number,
cycling through 6 priority industries defined in target-markets.md.
"""

import datetime
import sys

INDUSTRIES = [
    "warehouses hiring Cleveland TN",
    "restaurants hiring Cleveland TN",
    "retail stores hiring Cleveland TN",
    "manufacturing jobs Cleveland TN",
    "nursing homes hiring Cleveland TN",
    "hotels hiring Cleveland TN",
]

def main():
    week = datetime.date.today().isocalendar()[1]
    query = INDUSTRIES[week % len(INDUSTRIES)]
    print(query)


if __name__ == '__main__':
    main()
