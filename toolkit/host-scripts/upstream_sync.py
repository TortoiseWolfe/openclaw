#!/usr/bin/env python3
"""Weekly upstream sync — checks openclaw/openclaw for releases, attempts merge + security cherry-picks.

Runs on the HOST (not inside Docker) because it needs git access to the repo.
Triggered by crontab: 30 11 * * 6 (Saturdays 11:30 AM ET)

Flow:
  1. Load local version from package.json
  2. Fetch releases from GitHub API, classify urgency
  3. Ensure `upstream` remote exists, git fetch upstream
  4. Create upstream-sync/YYYY-MM-DD branch, attempt merge
  5. For security releases: cherry-pick onto security-patch/YYYY-MM-DD branch
  6. Write status JSON + print markdown summary
"""

import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

# ── Configuration ────────────────────────────────────────────────────

REPO_DIR = Path(__file__).resolve().parent.parent.parent  # openclaw repo root
PACKAGE_JSON = REPO_DIR / "package.json"
STATUS_FILE = Path.home() / ".openclaw" / "upstream-status.json"
LOG_FILE = Path.home() / ".openclaw" / "upstream-sync.log"

UPSTREAM_REMOTE = "upstream"
UPSTREAM_URL = "https://github.com/openclaw/openclaw.git"
UPSTREAM_BRANCH = "main"
UPSTREAM_API = "https://api.github.com/repos/openclaw/openclaw"

SECURITY_KEYWORDS = [
    "security", "CVE", "SSRF", "XSS", "injection", "vulnerability",
    "exploit", "patch", "critical", "auth bypass", "remote code execution",
    "RCE", "privilege escalation", "denial of service", "DoS",
    "path traversal", "directory traversal", "CSRF", "sanitiz",
    "token redaction", "sandbox",
]

BREAKING_KEYWORDS = [
    "BREAKING", "breaking change", "migration required",
    "deprecated", "removed",
]

USER_AGENT = "OpenClaw-UpstreamSync/1.0"


# ── Logging ──────────────────────────────────────────────────────────

def log(msg):
    """Print timestamped message to stdout (captured by cron log redirect)."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ── Git helpers ──────────────────────────────────────────────────────

def git(*args, check=True, capture=True):
    """Run a git command in the repo directory. Returns stdout string."""
    cmd = ["git", "-C", str(REPO_DIR)] + list(args)
    result = subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        check=check,
        timeout=120,
    )
    if capture:
        return result.stdout.strip()
    return ""


def git_rc(*args):
    """Run a git command and return (returncode, stdout, stderr)."""
    cmd = ["git", "-C", str(REPO_DIR)] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def ensure_upstream_remote():
    """Add upstream remote if not already configured."""
    remotes = git("remote", "-v")
    if UPSTREAM_REMOTE not in remotes:
        log(f"Adding remote '{UPSTREAM_REMOTE}' → {UPSTREAM_URL}")
        git("remote", "add", UPSTREAM_REMOTE, UPSTREAM_URL)
    else:
        log(f"Remote '{UPSTREAM_REMOTE}' already configured")


def fetch_upstream():
    """Fetch latest from upstream."""
    log("Fetching upstream...")
    git("fetch", UPSTREAM_REMOTE, "--prune", check=True, capture=False)
    log("Fetch complete")


def current_branch():
    """Get current branch name."""
    return git("rev-parse", "--abbrev-ref", "HEAD")


def branch_exists(name):
    """Check if a local branch exists."""
    rc, _, _ = git_rc("rev-parse", "--verify", name)
    return rc == 0


def stash_if_dirty():
    """If working tree is dirty, return True (caller should abort). We don't auto-stash."""
    status = git("status", "--porcelain")
    return bool(status)


# ── HTTP helpers ─────────────────────────────────────────────────────

def fetch_json(url, timeout=15):
    """Fetch JSON from GitHub API."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


# ── Version helpers ──────────────────────────────────────────────────

def load_local_version():
    """Read version from local package.json."""
    with open(PACKAGE_JSON) as f:
        return json.load(f).get("version", "unknown")


def parse_version_date(version_str):
    """Parse YYYY.M.DD version to a comparable tuple. Returns None if unparseable."""
    m = re.match(r"^v?(\d{4})\.(\d{1,2})\.(\d{1,2})(?:-.*)?$", version_str)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def version_newer(upstream_v, local_v):
    """Return True if upstream version is newer than local."""
    up = parse_version_date(upstream_v)
    loc = parse_version_date(local_v)
    if up and loc:
        return up > loc
    return upstream_v != local_v


def days_between(v1, v2):
    """Estimate days between two YYYY.M.DD versions."""
    d1 = parse_version_date(v1)
    d2 = parse_version_date(v2)
    if d1 and d2:
        try:
            return abs((date(*d1) - date(*d2)).days)
        except ValueError:
            pass
    return None


# ── Release analysis ─────────────────────────────────────────────────

def scan_keywords(text, keywords):
    """Scan text for keyword matches (case-insensitive). Returns matched list."""
    if not text:
        return []
    return [kw for kw in keywords
            if re.search(re.escape(kw), text, re.IGNORECASE)]


def classify_urgency(body, name=""):
    """Classify a release: URGENT (security), REVIEW (breaking), or INFO."""
    combined = f"{name}\n{body or ''}"
    security = scan_keywords(combined, SECURITY_KEYWORDS)
    breaking = scan_keywords(combined, BREAKING_KEYWORDS)
    if security:
        return "URGENT", security
    if breaking:
        return "REVIEW", breaking
    return "INFO", []


def fetch_releases_since(local_version, max_pages=3):
    """Fetch all GitHub releases newer than local_version."""
    newer = []
    for page in range(1, max_pages + 1):
        url = f"{UPSTREAM_API}/releases?per_page=15&page={page}"
        try:
            releases = fetch_json(url)
        except Exception as e:
            log(f"  Warning: page {page} fetch failed: {e}")
            break
        if not releases:
            break
        for rel in releases:
            tag = rel.get("tag_name", "").lstrip("v")
            if version_newer(tag, local_version):
                newer.append(rel)
            else:
                return newer
    return newer


# ── Merge logic ──────────────────────────────────────────────────────

def attempt_merge(today_str):
    """Create upstream-sync branch and attempt merge. Returns result dict."""
    branch_name = f"upstream-sync/{today_str}"
    result = {
        "branch": branch_name,
        "status": "skipped",
        "conflicts": [],
        "message": "",
    }

    if branch_exists(branch_name):
        result["message"] = f"Branch {branch_name} already exists — skipping"
        log(result["message"])
        return result

    original_branch = current_branch()

    # Create branch from main
    log(f"Creating branch {branch_name} from main...")
    git("checkout", "-b", branch_name, "main")

    try:
        # --allow-unrelated-histories needed because openclaw is a squashed fork
        log(f"Merging upstream/{UPSTREAM_BRANCH}...")
        rc, stdout, stderr = git_rc("merge", f"{UPSTREAM_REMOTE}/{UPSTREAM_BRANCH}",
                                     "--no-edit", "--allow-unrelated-histories")

        if rc == 0:
            result["status"] = "clean"
            result["message"] = "Merge completed cleanly — review branch ready"
            log(result["message"])
        else:
            # Collect conflict info before aborting
            conflict_output = git("diff", "--name-only", "--diff-filter=U")
            result["conflicts"] = conflict_output.split("\n") if conflict_output else []
            result["status"] = "conflicts"
            result["message"] = f"Merge has {len(result['conflicts'])} conflict(s)"
            log(result["message"])
            for cf in result["conflicts"][:20]:
                log(f"  conflict: {cf}")
            if len(result["conflicts"]) > 20:
                log(f"  ... and {len(result['conflicts']) - 20} more")
            # Clean up: abort merge and reset
            git_rc("merge", "--abort")
            git_rc("reset", "--hard", "HEAD")
    finally:
        # Always return to original branch
        git("checkout", original_branch)

    return result


# ── Cherry-pick logic ────────────────────────────────────────────────

def find_security_commits(local_version):
    """Find commits in upstream that mention security keywords in their message."""
    vd = parse_version_date(local_version)
    if not vd:
        return []

    since_date = date(*vd).isoformat()
    # Multiple --grep flags are OR'd by default in git log
    rc, log_output, _ = git_rc("log", f"{UPSTREAM_REMOTE}/{UPSTREAM_BRANCH}",
                               f"--since={since_date}", "--oneline", "--no-merges",
                               "--grep=security", "--grep=CVE", "--grep=SSRF",
                               "--grep=vulnerability", "--grep=XSS",
                               "--grep=injection", "--grep=sanitiz")

    if rc != 0 or not log_output:
        return []

    commits = []
    for line in log_output.split("\n"):
        if line.strip():
            parts = line.split(" ", 1)
            commits.append({
                "hash": parts[0],
                "message": parts[1] if len(parts) > 1 else "",
            })
    return commits


def attempt_cherry_picks(today_str, security_commits):
    """Cherry-pick security commits onto a dedicated branch. Returns result dict."""
    branch_name = f"security-patch/{today_str}"
    result = {
        "branch": branch_name,
        "attempted": len(security_commits),
        "succeeded": [],
        "failed": [],
    }

    if not security_commits:
        result["status"] = "no_commits"
        return result

    if branch_exists(branch_name):
        result["status"] = "skipped"
        result["message"] = f"Branch {branch_name} already exists"
        log(result["message"])
        return result

    original_branch = current_branch()

    log(f"Creating branch {branch_name} from main...")
    git("checkout", "-b", branch_name, "main")

    try:
        for commit in security_commits:
            sha = commit["hash"]
            msg = commit["message"][:80]
            log(f"  Cherry-picking {sha} ({msg})...")

            rc, stdout, stderr = git_rc("cherry-pick", sha, "--no-commit")
            if rc == 0:
                # Commit the cherry-pick
                rc2, _, _ = git_rc("commit", "--no-edit", "-m",
                                   f"cherry-pick upstream security: {sha}\n\n{commit['message']}")
                if rc2 == 0:
                    result["succeeded"].append(commit)
                    log("    OK")
                else:
                    git_rc("cherry-pick", "--abort")
                    git_rc("reset", "--hard", "HEAD")
                    result["failed"].append({**commit, "reason": "commit failed"})
                    log("    FAILED (commit)")
            else:
                git_rc("cherry-pick", "--abort")
                git_rc("reset", "--hard", "HEAD")
                result["failed"].append({**commit, "reason": "conflict"})
                log("    FAILED (conflict)")

        result["status"] = "done"
    finally:
        git("checkout", original_branch)

    return result


# ── Output ───────────────────────────────────────────────────────────

def build_status(local_version, latest_tag, missed_releases,
                 merge_result, cherry_result):
    """Build the full status dict."""
    gap = days_between(latest_tag, local_version)
    is_current = not version_newer(latest_tag, local_version)

    overall_urgency = "OK" if is_current else "INFO"
    all_security = []
    all_breaking = []
    release_summaries = []

    for rel in missed_releases:
        tag = rel.get("tag_name", "").lstrip("v")
        urgency, hits = classify_urgency(rel.get("body", ""), rel.get("name", ""))
        if urgency == "URGENT":
            overall_urgency = "URGENT"
            all_security.extend(hits)
        elif urgency == "REVIEW" and overall_urgency != "URGENT":
            overall_urgency = "REVIEW"
            all_breaking.extend(hits)
        release_summaries.append({
            "version": tag,
            "name": rel.get("name", ""),
            "date": rel.get("published_at", "")[:10],
            "urgency": urgency,
            "keywords": hits,
            "url": rel.get("html_url", ""),
        })

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "local_version": local_version,
        "latest_upstream": latest_tag,
        "is_current": is_current,
        "days_behind": gap,
        "releases_behind": len(missed_releases),
        "urgency": overall_urgency,
        "security_keywords": list(set(all_security)),
        "breaking_keywords": list(set(all_breaking)),
        "merge": merge_result,
        "cherry_pick": cherry_result,
        "missed_releases": release_summaries[:20],  # cap at 20
    }


def format_summary(status):
    """Human-readable markdown summary."""
    lines = ["# Upstream Sync Report", ""]
    lines.append(f"**Local:** {status['local_version']}")
    lines.append(f"**Upstream:** {status['latest_upstream']}")
    lines.append(f"**Urgency:** {status['urgency']}")

    if status["is_current"]:
        lines.append("\nUp to date. No action needed.")
        return "\n".join(lines)

    lines.append(f"**Behind:** {status['releases_behind']} release(s), "
                 f"~{status['days_behind'] or '?'} days")

    # Merge result
    m = status["merge"]
    lines.append("\n## Merge Attempt")
    lines.append(f"**Branch:** `{m['branch']}`")
    lines.append(f"**Result:** {m['status']}")
    if m.get("conflicts"):
        lines.append(f"**Conflicts ({len(m['conflicts'])}):**")
        for cf in m["conflicts"][:20]:
            lines.append(f"  - `{cf}`")
        if len(m["conflicts"]) > 20:
            lines.append(f"  - ... and {len(m['conflicts']) - 20} more")

    # Cherry-pick result
    cp = status.get("cherry_pick", {})
    if cp and cp.get("attempted", 0) > 0:
        lines.append("\n## Security Cherry-Picks")
        lines.append(f"**Branch:** `{cp['branch']}`")
        lines.append(f"**Attempted:** {cp['attempted']}")
        lines.append(f"**Succeeded:** {len(cp.get('succeeded', []))}")
        lines.append(f"**Failed:** {len(cp.get('failed', []))}")
        for c in cp.get("failed", [])[:10]:
            lines.append(f"  - `{c['hash']}` — {c.get('reason', '?')}: {c['message'][:60]}")

    # Urgency alerts
    if status["urgency"] == "URGENT":
        lines.append("\n## URGENT: Security Releases Detected")
        lines.append(f"Keywords: {', '.join(status['security_keywords'])}")
    elif status["urgency"] == "REVIEW":
        lines.append("\n## REVIEW: Breaking Changes Detected")
        lines.append(f"Keywords: {', '.join(status['breaking_keywords'])}")

    # Release list (abbreviated)
    if status["missed_releases"]:
        lines.append(f"\n## Missed Releases ({len(status['missed_releases'])})")
        for rel in status["missed_releases"][:10]:
            badge = {"URGENT": " [SECURITY]", "REVIEW": " [BREAKING]", "INFO": ""}
            lines.append(f"- **{rel['version']}** ({rel['date']}){badge[rel['urgency']]} "
                         f"— {rel['name'] or 'No title'}")

    return "\n".join(lines)


def write_status(status):
    """Write status JSON to file."""
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATUS_FILE, "w") as f:
        json.dump(status, f, indent=2)
    log(f"Status written to {STATUS_FILE}")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    log("=== upstream sync ===")
    today_str = date.today().isoformat()

    # Preflight: check for dirty working tree
    if stash_if_dirty():
        log("ERROR: Working tree has uncommitted changes. Commit or stash first.")
        log("Aborting to avoid mixing upstream changes with local work.")
        sys.exit(1)

    # 1. Local version
    try:
        local_version = load_local_version()
    except FileNotFoundError:
        log(f"ERROR: {PACKAGE_JSON} not found")
        sys.exit(1)
    log(f"Local version: {local_version}")

    # 2. Check upstream releases
    try:
        latest_resp = fetch_json(f"{UPSTREAM_API}/releases/latest")
        latest_tag = latest_resp.get("tag_name", "unknown").lstrip("v")
    except Exception as e:
        log(f"ERROR: Failed to fetch latest release: {e}")
        sys.exit(1)
    log(f"Latest upstream: {latest_tag}")

    if not version_newer(latest_tag, local_version):
        log("Up to date with upstream")
        status = build_status(local_version, latest_tag, [],
                              {"branch": "", "status": "up_to_date", "conflicts": [],
                               "message": "Already current"},
                              {"status": "not_needed", "attempted": 0})
        write_status(status)
        print(format_summary(status))
        return

    missed = fetch_releases_since(local_version)
    log(f"Behind by {len(missed)} release(s)")

    # 3. Git remote + fetch
    ensure_upstream_remote()
    fetch_upstream()

    # 4. Attempt merge
    merge_result = attempt_merge(today_str)

    # 5. Security cherry-picks (only if any release is URGENT)
    has_security = any(
        classify_urgency(r.get("body", ""), r.get("name", ""))[0] == "URGENT"
        for r in missed
    )
    cherry_result = {"status": "not_needed", "attempted": 0,
                     "succeeded": [], "failed": [], "branch": ""}

    if has_security:
        log("Security releases detected — attempting cherry-picks...")
        security_commits = find_security_commits(local_version)
        log(f"Found {len(security_commits)} security-related commit(s)")
        if security_commits:
            cherry_result = attempt_cherry_picks(today_str, security_commits)

    # 6. Build and write status
    status = build_status(local_version, latest_tag, missed,
                          merge_result, cherry_result)
    write_status(status)
    print(format_summary(status))

    log("=== sync complete ===")


if __name__ == "__main__":
    os.chdir(REPO_DIR)
    main()
