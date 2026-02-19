"""Shared utilities for job search scripts.

Extracted from job_search.py and triage_saved_jobs.py to eliminate
diverged location_gate() copies (CODE-REVIEW #27).
"""

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
    "alpharetta", "athens", "maryville", "oak ridge",
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
