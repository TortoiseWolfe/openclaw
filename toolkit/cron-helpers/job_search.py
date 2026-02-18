#!/usr/bin/env python3
"""Job search with term rotation and results persistence.

Each invocation:
1. Picks 1 weighted-random search term (avoiding today's already-searched terms)
2. Calls search_jobs via MCP gateway
3. Filters results by location, deduplicates against tracker
4. Scores matches and appends new leads to tracker.md
5. Updates term-performance.md and daily report

Designed for 5 daily cron invocations spread across 10 hours to mimic
natural LinkedIn browsing behavior (anti-bot pacing).
"""

import json
import os
import random
import re
import sys
from datetime import date

from content_security import detect_suspicious, sanitize_field

# Add toolkit dir to path for mcp_client import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import MCPClient, MCPError

# ── Paths (inside Docker container) ──────────────────────────────────

SEARCH_DIR = "/home/node/repos/TranScripts/Career/JobSearch/private"
TRACKER = os.path.join(SEARCH_DIR, "tracker.md")
TERM_PERF = os.path.join(SEARCH_DIR, "term-performance.md")


# ── Term selection ───────────────────────────────────────────────────

def parse_terms(path):
    """Parse term-performance.md into list of term dicts."""
    with open(path) as f:
        content = f.read()

    terms = []
    pattern = re.compile(
        r"^\|\s*([^|]+?)\s*\|"   # term
        r"\s*(\d+)\s*\|"         # searches
        r"\s*(\d+)\s*\|"         # jobs found
        r"\s*(\d+)\s*\|"         # passed filter
        r"\s*(\d+)\s*\|"         # avg score
        r"\s*(\d+)\s*\|"         # best score
        r"\s*([^|]*?)\s*\|"      # last searched
        r"\s*(\w+)\s*\|",        # status
        re.MULTILINE,
    )

    for m in pattern.finditer(content):
        term = m.group(1).strip()
        if term.lower() in ("term", "---", "----"):
            continue
        terms.append({
            "term": term,
            "searches": int(m.group(2)),
            "jobs_found": int(m.group(3)),
            "passed_filter": int(m.group(4)),
            "avg_score": int(m.group(5)),
            "best_score": int(m.group(6)),
            "last_searched": m.group(7).strip(),
            "status": m.group(8).strip(),
        })

    return terms


def get_today_searched(today):
    """Read today's daily report to find already-searched terms."""
    report_path = os.path.join(SEARCH_DIR, f"daily-search-{today.isoformat()}.md")
    if not os.path.exists(report_path):
        return set()

    with open(report_path) as f:
        content = f.read()

    searched = set()
    for m in re.finditer(r"^\|\s*([^|]+?)\s*\|", content, re.MULTILINE):
        term = m.group(1).strip()
        if term.lower() not in ("term", "---", "----", ""):
            searched.add(term.lower())

    return searched


def pick_term(terms, already_searched):
    """Pick 1 weighted-random term, excluding already-searched today."""
    weights = {"hot": 3.0, "active": 1.0, "cold": 0.3}
    untested_bonus = 2.0

    candidates = []
    term_weights = []

    for t in terms:
        if t["term"].lower() in already_searched:
            continue
        w = weights.get(t["status"], 1.0)
        if t["searches"] == 0:
            w = untested_bonus
        candidates.append(t)
        term_weights.append(w)

    if not candidates:
        return None

    return random.choices(candidates, weights=term_weights, k=1)[0]


# ── Location gate ────────────────────────────────────────────────────

# Locations that auto-pass
PASS_LOCATIONS = {
    "remote", "united states (remote)", "united states",
    "cleveland", "chattanooga", "ooltewah", "hixson",
    "east ridge", "signal mountain", "soddy-daisy",
}

# Locations that pass with a "CHECK" note for user review
CHECK_LOCATIONS = {
    "knoxville", "nashville", "atlanta", "murfreesboro",
    "franklin", "cookeville", "dalton", "rome",
}


def location_gate(location):
    """Classify job location.

    Returns:
        ("pass", score_bonus)  -- Remote or local
        ("check", score_bonus) -- Regional, needs user review
        ("reject", 0)          -- Outside radius
    """
    if not location:
        return "check", 15  # unknown location, user should check

    loc = location.lower().strip()

    # Remote keywords
    if "remote" in loc:
        return "pass", 30

    # Check exact city matches
    for city in PASS_LOCATIONS:
        if city in loc:
            return "pass", 25

    for city in CHECK_LOCATIONS:
        if city in loc:
            return "check", 15

    # Tennessee generic
    if ", tn" in loc or "tennessee" in loc:
        return "check", 15

    return "reject", 0


# ── Scoring ──────────────────────────────────────────────────────────

SKILL_KEYWORDS = {
    "react": 8, "typescript": 7, "node.js": 6, "node": 5,
    "javascript": 5, "next.js": 6, "c#": 6, ".net": 5,
    "docker": 4, "aws": 4, "python": 4, "postgresql": 4,
    "supabase": 3, "graphql": 3, "rest": 2, "api": 2,
    "tailwind": 2, "css": 1, "html": 1, "git": 1,
}

TITLE_KEYWORDS = {
    "developer": 20, "engineer": 20, "programmer": 15,
    "senior": 15, "lead": 10, "principal": 10, "staff": 10,
    "junior": 10, "jr": 10, "entry": 5, "intern": 5,
}


def score_job(job):
    """Score a job 0-100 based on skills match, location, and title."""
    title = (job.get("job_title") or "").lower()
    location = (job.get("location") or "").lower()
    description = (job.get("job_description") or "").lower()

    # Combine all text for keyword matching
    all_text = f"{title} {description}"

    # Skills score (max 50)
    skills_score = 0
    for keyword, points in SKILL_KEYWORDS.items():
        if keyword in all_text:
            skills_score += points
    skills_score = min(skills_score, 50)

    # Location score (max 30)
    _, loc_score = location_gate(job.get("location"))

    # Title score (max 20)
    title_score = 0
    for keyword, points in TITLE_KEYWORDS.items():
        if keyword in title:
            title_score = max(title_score, points)

    return min(skills_score + loc_score + title_score, 100)


# ── Dedup ────────────────────────────────────────────────────────────

_TRACKER_ROW = re.compile(
    r"^\|\s*[^|]+\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|",
    re.MULTILINE,
)


def load_tracked_companies(path):
    """Load set of (company, role_prefix) from tracker.md for dedup."""
    tracked = set()
    if not os.path.exists(path):
        return tracked

    with open(path) as f:
        content = f.read()

    for m in _TRACKER_ROW.finditer(content):
        company = m.group(1).strip().lower()
        role = m.group(2).strip().lower()[:30]
        if company and company not in ("company", "---"):
            tracked.add((company, role))

    return tracked


def is_duplicate(job, tracked):
    """Check if a job is already in the tracker."""
    company = (job.get("company") or "").lower()
    title = (job.get("job_title") or "").lower()
    # Clean duplicated titles (LinkedIn sometimes doubles them)
    title = title.split("\n")[0].strip()

    if not company:
        return False

    for tc, tr in tracked:
        if company == tc and (tr in title or title[:30] in tr):
            return True

    return False


# ── Results persistence ──────────────────────────────────────────────

def append_to_tracker(jobs, today):
    """Append new job leads to tracker.md."""
    if not jobs:
        return

    lines = []
    for job in jobs:
        title = sanitize_field(job.get("job_title") or "Unknown", 100)
        company = sanitize_field(job.get("company") or "Unknown", 80)
        score = job.get("_score", 0)
        url = job.get("linkedin_url") or "--"
        loc_status, _ = location_gate(job.get("location"))
        note = f"LEAD — {job.get('location', '?')}"
        if loc_status == "check":
            note += ", needs location review"
        status = "lead"

        lines.append(
            f"| {today.isoformat()} | {company} | {title} | {score} "
            f"| linkedin | {status} | {url} | -- | -- | {note} |"
        )

    with open(TRACKER, "a") as f:
        f.write("\n".join(lines) + "\n")


def update_term_performance(term_name, jobs_found, passed_filter, scores, today):
    """Update a term's stats in term-performance.md."""
    with open(TERM_PERF) as f:
        content = f.read()

    # Escape special regex characters in term name
    escaped = re.escape(term_name)

    pattern = re.compile(
        r"^(\|\s*" + escaped + r"\s*\|)"
        r"\s*(\d+)\s*\|"    # old searches
        r"\s*(\d+)\s*\|"    # old jobs found
        r"\s*(\d+)\s*\|"    # old passed filter
        r"\s*(\d+)\s*\|"    # old avg score
        r"\s*(\d+)\s*\|"    # old best score
        r"\s*[^|]*\s*\|"    # old last searched
        r"\s*(\w+)\s*\|",   # old status
        re.MULTILINE,
    )

    def replacer(m):
        prefix = m.group(1)
        old_searches = int(m.group(2))
        old_found = int(m.group(3))
        old_passed = int(m.group(4))
        old_avg = int(m.group(5))
        old_best = int(m.group(6))
        old_status = m.group(7).strip()

        new_searches = old_searches + 1
        new_found = old_found + jobs_found
        new_passed = old_passed + passed_filter

        # Recalculate avg score across all passed-filter jobs
        if new_passed > 0 and scores:
            total_score = old_avg * old_passed + sum(scores)
            new_avg = total_score // new_passed
        else:
            new_avg = old_avg

        new_best = max(old_best, max(scores) if scores else 0)

        # Auto-promote/demote
        new_status = old_status
        if new_searches >= 3 and new_passed > 0 and new_avg >= 50:
            new_status = "hot"
        elif new_searches >= 5 and new_passed == 0:
            new_status = "cold"
        elif old_status == "cold" and passed_filter > 0:
            new_status = "active"

        return (
            f"{prefix} {new_searches} | {new_found} | {new_passed} "
            f"| {new_avg} | {new_best} | {today.isoformat()} | {new_status} |"
        )

    new_content, count = pattern.subn(replacer, content, count=1)
    if count == 0:
        print(f"  WARNING: Could not find term '{term_name}' in term-performance.md")
        return

    with open(TERM_PERF, "w") as f:
        f.write(new_content)


def write_daily_report(term_name, jobs_found, passed_filter, top_score,
                       new_leads, dupes_skipped, today):
    """Append to today's daily search report."""
    report_path = os.path.join(SEARCH_DIR, f"daily-search-{today.isoformat()}.md")

    if not os.path.exists(report_path):
        header = f"# Daily Search Report — {today.isoformat()}\n\n"
        header += "| Term | Jobs Found | Passed Filter | New Leads | Dupes | Top Score |\n"
        header += "|------|-----------|---------------|-----------|-------|----------|\n"
        with open(report_path, "w") as f:
            f.write(header)

    line = (
        f"| {term_name} | {jobs_found} | {passed_filter} "
        f"| {new_leads} | {dupes_skipped} | {top_score or '--'} |\n"
    )
    with open(report_path, "a") as f:
        f.write(line)


# ── Main ─────────────────────────────────────────────────────────────

def main():
    today = date.today()

    # Parse terms and find what's already been searched today
    try:
        terms = parse_terms(TERM_PERF)
    except FileNotFoundError:
        print("ERROR: term-performance.md not found", file=sys.stderr)
        sys.exit(1)

    if not terms:
        print("ERROR: No terms found in term-performance.md", file=sys.stderr)
        sys.exit(1)

    already_searched = get_today_searched(today)
    print(f"Terms available: {len(terms)}, already searched today: {len(already_searched)}")

    # Pick a term
    term = pick_term(terms, already_searched)
    if term is None:
        print("All terms searched today. Nothing to do.")
        return

    print(f"Selected term: \"{term['term']}\" (status: {term['status']}, "
          f"searches: {term['searches']})")

    # Load tracker for dedup
    tracked = load_tracked_companies(TRACKER)
    print(f"Tracker has {len(tracked)} company/role pairs for dedup")

    # Connect to MCP and search
    try:
        with MCPClient() as mcp:
            print(f"Searching LinkedIn for: \"{term['term']}\"")
            raw_result = mcp.call_tool("search_jobs", {
                "search_term": term["term"],
            })
    except MCPError as e:
        print(f"MCP error: {e}", file=sys.stderr)
        # Still update the daily report with 0 results
        write_daily_report(term["term"], 0, 0, None, 0, 0, today)
        update_term_performance(term["term"], 0, 0, [], today)
        sys.exit(1)

    # Parse results
    try:
        jobs = json.loads(raw_result)
        if not isinstance(jobs, list):
            jobs = []
    except (json.JSONDecodeError, TypeError):
        print(f"WARNING: Could not parse search results as JSON")
        jobs = []

    print(f"Raw results: {len(jobs)} jobs")

    # Filter, score, and dedup
    new_leads = []
    dupes_skipped = 0
    location_rejected = 0
    scores = []

    for job in jobs:
        # Location gate
        loc_result, _ = location_gate(job.get("location"))
        if loc_result == "reject":
            location_rejected += 1
            continue

        # Dedup
        if is_duplicate(job, tracked):
            dupes_skipped += 1
            continue

        # Score
        score = score_job(job)
        job["_score"] = score
        scores.append(score)

        if score >= 30:  # low threshold — user reviews leads manually
            new_leads.append(job)
            # Add to tracked set to prevent dupes within this run
            company = (job.get("company") or "").lower()
            title = (job.get("job_title") or "").lower().split("\n")[0][:30]
            tracked.add((company, title))

    passed_filter = len(scores)
    top_score = max(scores) if scores else None

    print(f"\nResults: {len(jobs)} found, {location_rejected} rejected (location), "
          f"{dupes_skipped} dupes, {passed_filter} passed filter")
    print(f"New leads: {len(new_leads)}, top score: {top_score or '--'}")

    # Save results
    if new_leads:
        append_to_tracker(new_leads, today)
        print(f"Appended {len(new_leads)} leads to tracker.md")

        for lead in new_leads:
            title = sanitize_field(lead.get("job_title") or "?", 100)
            company = sanitize_field(lead.get("company") or "?", 80)
            loc = sanitize_field(lead.get("location") or "?", 80)
            # Check for injection in external fields
            for field_val in (title, company, loc):
                flags = detect_suspicious(field_val)
                if flags:
                    print(f"  [security] Suspicious content in job field: {flags}",
                          file=sys.stderr)
            print(f"  [{lead['_score']}] {company} — {title} ({loc})")

    # Update term stats
    update_term_performance(term["term"], len(jobs), passed_filter,
                           scores, today)

    # Write daily report
    write_daily_report(term["term"], len(jobs), passed_filter, top_score,
                       len(new_leads), dupes_skipped, today)

    print(f"\nDone. Term \"{term['term']}\" processed.")


if __name__ == "__main__":
    main()
