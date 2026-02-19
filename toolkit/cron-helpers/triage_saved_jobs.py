#!/usr/bin/env python3
"""Triage LinkedIn saved jobs with human-paced browser lookups.

Reads job IDs from tracker.md, visits each listing via Playwright
(browser_navigate), parses the page title for status/location,
and writes results to a triage report. Paces requests at 3-5 minutes
apart to mimic human browsing behavior.

Features:
- Short-lived MCP connections (one per job, like job_search.py)
- Lock file prevents concurrent instances
- Resume capability: skips already-processed jobs if report exists

Usage (inside Docker):
    python3 /app/toolkit/cron-helpers/triage_saved_jobs.py [--month 2026-01]

Outputs:
    ~/repos/TranScripts/Career/JobSearch/private/triage-YYYY-MM-DD.md
"""

import atexit
import json
import os
import random
import re
import sys
import time
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from content_security import detect_suspicious, sanitize_field
from mcp_client import MCPClient, MCPError

# ── Paths (inside Docker container) ──────────────────────────────────

SEARCH_DIR = "/home/node/repos/TranScripts/Career/JobSearch/private"
TRACKER = os.path.join(SEARCH_DIR, "tracker.md")
LOCK_FILE = os.path.join(SEARCH_DIR, "triage.lock")

# ── Lock file ────────────────────────────────────────────────────────

def acquire_lock():
    """Acquire lock file. Abort if another instance is running."""
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE) as f:
                old_pid = int(f.read().strip())
            # Check if process is still alive
            os.kill(old_pid, 0)
            print(f"Another instance is running (PID {old_pid}). Aborting.",
                  flush=True)
            sys.exit(1)
        except (ValueError, ProcessLookupError, PermissionError):
            # Stale lock file — old process is gone
            print(f"Removing stale lock file (old PID gone).", flush=True)

    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    atexit.register(release_lock)


def release_lock():
    """Remove lock file."""
    try:
        os.remove(LOCK_FILE)
    except FileNotFoundError:
        pass


# ── Resume: parse existing report ────────────────────────────────────

def get_completed_indices(report_path):
    """Parse existing report and return set of completed job indices (1-based)."""
    completed = set()
    if not os.path.exists(report_path):
        return completed

    with open(report_path) as f:
        for line in f:
            # Match data rows: | {number} | ...
            m = re.match(r"^\|\s*(\d+)\s*\|", line)
            if m:
                completed.add(int(m.group(1)))

    return completed


# ── Location gate (from job_search.py) ───────────────────────────────

PASS_LOCATIONS = {
    "remote", "united states (remote)", "united states",
    "cleveland", "chattanooga", "ooltewah", "hixson",
    "east ridge", "signal mountain", "soddy-daisy",
}

CHECK_LOCATIONS = {
    "knoxville", "nashville", "atlanta", "murfreesboro",
    "franklin", "cookeville", "dalton", "rome",
    "alpharetta", "athens", "maryville", "oak ridge",
}


def location_gate(location):
    if not location:
        return "check", 15
    loc = location.lower().strip()
    if "remote" in loc:
        return "pass", 30
    for city in PASS_LOCATIONS:
        if city in loc:
            return "pass", 25
    for city in CHECK_LOCATIONS:
        if city in loc:
            return "check", 15
    if ", tn" in loc or "tennessee" in loc:
        return "check", 15
    return "reject", 0


# ── Title-based scoring (no description available without login) ─────

TITLE_KEYWORDS = {
    "react": 8, "typescript": 7, "node": 5, "next.js": 6,
    "javascript": 5, "python": 4, "c#": 6, ".net": 5,
    "docker": 4, "aws": 4, "ai": 4, "ml": 3,
    "developer": 20, "engineer": 20, "programmer": 15,
    "senior": 5, "lead": 5, "principal": 5, "staff": 5,
    "junior": 10, "jr": 10, "entry": 5, "intern": 5,
    "designer": 10, "architect": 10, "analyst": 5,
    "frontend": 8, "front-end": 8, "front end": 8,
    "full stack": 7, "fullstack": 7, "backend": 5,
    "web": 5, "software": 5, "test": 3, "qa": 3,
}


def score_title(title):
    """Score based on title keywords only (no description without login)."""
    t = title.lower()
    score = 0
    matched = []
    for keyword, points in TITLE_KEYWORDS.items():
        if keyword in t:
            score += points
            matched.append(keyword)
    return min(score, 100), matched


# ── Parse browser_navigate output ────────────────────────────────────

def parse_nav_result(nav_text):
    """Extract job info from browser_navigate snapshot.

    Page title format when active:
        "{Company} hiring {Title} in {Location} | LinkedIn"
    When closed/unavailable, title is different or page redirects.
    """
    info = {"active": False, "title": "", "company": "", "location": ""}

    # Extract page title
    title_match = re.search(r"Page Title:\s*(.+)", nav_text)
    if not title_match:
        return info

    page_title = sanitize_field(title_match.group(1).strip(), 200)
    flags = detect_suspicious(page_title)
    if flags:
        print(f"  [security] Suspicious content in page title: {flags}",
              file=sys.stderr)

    # Check for active job listing pattern
    # "{Company} hiring {Title} in {Location} | LinkedIn"
    job_match = re.match(
        r"^(.+?)\s+hiring\s+(.+?)\s+in\s+(.+?)\s*\|\s*LinkedIn$",
        page_title,
    )
    if job_match:
        info["active"] = True
        info["company"] = job_match.group(1).strip()
        info["title"] = job_match.group(2).strip()
        info["location"] = job_match.group(3).strip()
        return info

    # Some listings show as "{Title} | {Company} | LinkedIn"
    alt_match = re.match(r"^(.+?)\s*\|\s*(.+?)\s*\|\s*LinkedIn$", page_title)
    if alt_match:
        info["active"] = True
        info["title"] = alt_match.group(1).strip()
        info["company"] = alt_match.group(2).strip()
        return info

    # Check for closed/redirect indicators
    if "no longer accepting" in page_title.lower():
        info["title"] = page_title
        return info
    if "sign in" in page_title.lower() or "join" in page_title.lower():
        # LinkedIn blocked or redirected to login
        info["title"] = page_title
        return info

    # Unknown format — might still be active
    info["title"] = page_title
    return info


# ── Extract job IDs from tracker ─────────────────────────────────────

def get_lead_jobs(month_filter=None):
    """Read tracker.md and return list of lead jobs."""
    jobs = []
    with open(TRACKER) as f:
        for line in f:
            if "| lead |" not in line or "linkedin-saved" not in line:
                continue
            if month_filter and f"| {month_filter}" not in line:
                continue

            m = re.search(r"jobs/view/(\d+)", line)
            if not m:
                continue
            job_id = m.group(1)

            cols = [c.strip() for c in line.split("|")]
            if len(cols) >= 4:
                jobs.append({
                    "job_id": job_id,
                    "saved_date": cols[1],
                    "company": cols[2],
                    "title": cols[3],
                })

    return jobs


# ── Main ─────────────────────────────────────────────────────────────

def main():
    month_filter = None
    if len(sys.argv) > 2 and sys.argv[1] == "--month":
        month_filter = sys.argv[2]

    # Lock file — prevent concurrent runs
    acquire_lock()

    today = date.today()
    report_path = os.path.join(SEARCH_DIR, f"triage-{today.isoformat()}.md")

    jobs = get_lead_jobs(month_filter)
    if not jobs:
        print(f"No leads found{f' for {month_filter}' if month_filter else ''}.")
        sys.exit(0)

    # Check for existing report (resume capability)
    completed = get_completed_indices(report_path)
    resuming = len(completed) > 0
    remaining = len(jobs) - len(completed)

    if resuming:
        print(f"Resuming: {len(completed)} jobs already done, "
              f"{remaining} remaining", flush=True)
    else:
        print(f"Found {len(jobs)} leads to triage"
              f"{f' for {month_filter}' if month_filter else ''}", flush=True)

    print(f"Estimated time: {remaining * 4} minutes "
          f"({remaining * 4 / 60:.1f} hours)")
    print(f"Output: {report_path}")
    print(flush=True)

    # Write report header only if starting fresh
    if not resuming:
        with open(report_path, "w") as f:
            f.write(f"# Triage Report — {today.isoformat()}\n\n")
            if month_filter:
                f.write(f"Filter: {month_filter}\n\n")
            f.write("| # | Score | Company | Title | Location "
                    "| Loc Gate | Status | Matched | Notes |\n")
            f.write("|---|-------|---------|-------|----------"
                    "|----------|--------|---------|-------|\n")

    processed = 0
    skipped = 0
    closed = 0
    active_scores = []

    try:
        for i, job in enumerate(jobs):
            job_num = i + 1

            # Skip already-processed jobs
            if job_num in completed:
                skipped += 1
                continue

            job_id = job["job_id"]
            url = f"https://www.linkedin.com/jobs/view/{job_id}"
            print(f"[{job_num}/{len(jobs)}] {job['company']} — "
                  f"{job['title']}...", flush=True)

            # Fresh MCP connection per job (short-lived, like job_search.py)
            try:
                with MCPClient(read_timeout=180) as mcp:
                    nav_result = mcp.call_tool(
                        "browser_navigate", {"url": url}
                    )
                info = parse_nav_result(nav_result)
            except MCPError as e:
                print(f"  Error: {e}", flush=True)
                info = {"active": False, "title": "", "company": "",
                        "location": ""}
            except Exception as e:
                print(f"  Connection error: {e}", flush=True)
                info = {"active": False, "title": "", "company": "",
                        "location": ""}

            # Use parsed info, fall back to tracker data
            title = info["title"] or job["title"]
            company = info["company"] or job["company"]
            location = info["location"] or ""

            # Score and gate
            score, matched = score_title(title)
            loc_result, loc_bonus = location_gate(location)
            score = min(score + loc_bonus, 100)

            # Determine status
            if not info["active"]:
                status = "closed?"
                closed += 1
                notes = "Listing not found or no longer active"
            elif loc_result == "reject":
                status = "loc-reject"
                notes = f"Outside radius: {location}"
            else:
                status = "active"
                notes = location or "location unknown"
                active_scores.append(score)

            skills_str = ", ".join(matched[:6]) if matched else "--"

            # Append to report
            with open(report_path, "a") as f:
                f.write(f"| {job_num} | {score} | {company} | {title} "
                        f"| {location or '?'} | {loc_result} "
                        f"| {status} | {skills_str} | {notes} |\n")

            processed += 1
            print(f"  Score: {score}, Location: {loc_result} "
                  f"({location or '?'}), Status: {status}", flush=True)

            # Pace: 3-5 minutes between requests
            if i < len(jobs) - 1:
                delay = random.uniform(180, 300)
                resume_at = datetime.now().timestamp() + delay
                resume_str = datetime.fromtimestamp(
                    resume_at
                ).strftime("%H:%M:%S")
                print(f"  Next lookup at ~{resume_str} "
                      f"({int(delay)}s)...", flush=True)
                time.sleep(delay)

    except KeyboardInterrupt:
        print(f"\nInterrupted after {processed} new jobs.", flush=True)

    # Write summary
    with open(report_path, "a") as f:
        f.write(f"\n## Summary\n\n")
        f.write(f"- Processed this run: {processed}\n")
        if skipped:
            f.write(f"- Skipped (already done): {skipped}\n")
        f.write(f"- Total in report: {skipped + processed}/{len(jobs)}\n")
        f.write(f"- Likely closed: {closed}\n")
        f.write(f"- Active: {len(active_scores)}\n")
        if active_scores:
            f.write(f"- Score range: {min(active_scores)}"
                    f"-{max(active_scores)}\n")
            f.write(f"- Average score: "
                    f"{sum(active_scores) // len(active_scores)}\n")

    print(f"\nDone. Report: {report_path}", flush=True)
    print(f"Processed: {processed}, Skipped: {skipped}, "
          f"Closed: {closed}, Active: {len(active_scores)}", flush=True)


if __name__ == "__main__":
    main()
