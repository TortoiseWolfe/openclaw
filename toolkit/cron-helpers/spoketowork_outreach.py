#!/usr/bin/env python3
"""SpokeToWork outreach prep.

Reads agent-contacts.md, filters for contacts with status "researched"
that don't have an outreach draft yet, and prints a compact summary.

Designed for the spoketowork-outreach cron job (Thursdays 10:30 AM ET).
"""

import os
import re
import sys

CONTACTS_PATH = (
    "/home/node/repos/SpokeToWork---Business-Development"
    "/documents/agent-contacts.md"
)
DRAFTS_DIR = (
    "/home/node/repos/SpokeToWork---Business-Development"
    "/documents/outreach-drafts"
)


def parse_contacts(path):
    """Parse markdown table rows from agent-contacts.md."""
    if not os.path.exists(path):
        print(f"ERROR: contacts file not found at {path}", file=sys.stderr)
        sys.exit(1)

    with open(path) as f:
        lines = f.readlines()

    contacts = []
    for line in lines:
        line = line.strip()
        if not line.startswith("|") or line.startswith("| Date") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) < 8:
            continue
        contacts.append({
            "date": cells[0],
            "company": cells[1],
            "industry": cells[2],
            "score": cells[3],
            "contact": cells[4],
            "email": cells[5],
            "status": cells[6],
            "notes": cells[7],
        })
    return contacts


def has_draft(company):
    """Check if an outreach draft exists for this company."""
    if not os.path.isdir(DRAFTS_DIR):
        return False
    slug = re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-")
    for name in os.listdir(DRAFTS_DIR):
        if slug in name.lower():
            return True
    return False


def main():
    contacts = parse_contacts(CONTACTS_PATH)

    if not contacts:
        print("No contacts in tracker yet. Nothing to draft.")
        return

    researched = [c for c in contacts if c["status"].lower() == "researched"]
    if not researched:
        print(f"{len(contacts)} contacts tracked, none with status 'researched'.")
        return

    need_draft = [c for c in researched if not has_draft(c["company"])]
    if not need_draft:
        print(
            f"{len(researched)} researched contacts — all have outreach drafts."
        )
        return

    print(f"{len(need_draft)} researched contacts need outreach drafts:\n")
    for c in need_draft:
        print(f"- {c['company']} ({c['industry']}) — {c['contact']}, {c['email']}")
        if c["notes"]:
            print(f"  Notes: {c['notes']}")


if __name__ == "__main__":
    main()
