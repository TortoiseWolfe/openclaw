#!/usr/bin/env python3
"""Twitch OAuth token refresh helper.

Reads current tokens from ~/.openclaw/.env, refreshes via Twitch API,
and writes the new tokens back. Use this when the refresh token is still
valid but the access token has expired.

If the refresh token is dead (Twitch returns 400/401), you must
re-authenticate at https://twitchtokengenerator.com and paste the
new tokens into ~/.openclaw/.env manually.

Usage:
    python3 twitch_token_refresh.py              # refresh using stored tokens
    python3 twitch_token_refresh.py --check      # validate current access token only
    python3 twitch_token_refresh.py --force      # force refresh even if token is valid

Env file: ~/.openclaw/.env (auto-detected from $HOME)
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

DOT_ENV_PATH = os.path.join(
    os.environ.get("HOME", "/home/node"), ".openclaw", ".env",
)

REQUIRED_KEYS = [
    "OPENCLAW_TWITCH_CLIENT_ID",
    "OPENCLAW_TWITCH_CLIENT_SECRET",
    "OPENCLAW_TWITCH_REFRESH_TOKEN",
]


def read_env(path: str) -> dict[str, str]:
    """Read key=value pairs from a .env file."""
    result: dict[str, str] = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                result[key.strip()] = val.strip().strip("'\"")
    except FileNotFoundError:
        print(f"ERROR: {path} not found", file=sys.stderr)
        sys.exit(1)
    return result


def update_env(path: str, updates: dict[str, str]) -> None:
    """Update specific keys in a .env file, preserving everything else."""
    lines: list[str] = []
    try:
        with open(path) as f:
            lines = f.read().split("\n")
    except FileNotFoundError:
        pass

    updated_keys: set[str] = set()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            # Preserve any inline comment
            lines[i] = f"{key}={updates[key]}"
            updated_keys.add(key)

    # Append any new keys not found in the file
    for key, val in updates.items():
        if key not in updated_keys:
            lines.append(f"{key}={val}")

    output = "\n".join(lines)
    if not output.endswith("\n"):
        output += "\n"

    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        f.write(output)
    os.replace(tmp, path)


def validate_token(access_token: str, client_id: str) -> dict | None:
    """Validate an access token via Twitch API. Returns user info or None."""
    req = urllib.request.Request(
        "https://id.twitch.tv/oauth2/validate",
        headers={"Authorization": f"OAuth {access_token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError:
        return None


def refresh_token(client_id: str, client_secret: str, refresh_tok: str) -> dict:
    """Refresh the access token via Twitch API. Returns the full response."""
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_tok,
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode()

    req = urllib.request.Request(
        "https://id.twitch.tv/oauth2/token",
        data=data,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"ERROR: Twitch token refresh failed ({e.code}): {body}", file=sys.stderr)
        if e.code in (400, 401):
            print(
                "\nThe refresh token is DEAD. You must re-authenticate:\n"
                "  1. Go to https://twitchtokengenerator.com\n"
                "  2. Select 'Bot Chat Token' scopes\n"
                "  3. Copy the access token and refresh token\n"
                "  4. Update ~/.openclaw/.env:\n"
                "     OPENCLAW_TWITCH_ACCESS_TOKEN=<new_access_token>\n"
                "     OPENCLAW_TWITCH_REFRESH_TOKEN=<new_refresh_token>\n"
                "  5. Restart: docker compose up -d --force-recreate openclaw-gateway\n",
                file=sys.stderr,
            )
        sys.exit(1)


def main() -> None:
    import argparse
    import urllib.parse

    parser = argparse.ArgumentParser(description="Refresh Twitch OAuth tokens")
    parser.add_argument("--check", action="store_true", help="Validate current token only")
    parser.add_argument("--force", action="store_true", help="Force refresh even if valid")
    parser.add_argument("--env-file", default=DOT_ENV_PATH, help="Path to .env file")
    args = parser.parse_args()

    env = read_env(args.env_file)

    # Check required keys
    missing = [k for k in REQUIRED_KEYS if not env.get(k)]
    if missing and not args.check:
        print(f"ERROR: Missing required keys in {args.env_file}: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    client_id = env.get("OPENCLAW_TWITCH_CLIENT_ID", "")
    client_secret = env.get("OPENCLAW_TWITCH_CLIENT_SECRET", "")
    current_refresh = env.get("OPENCLAW_TWITCH_REFRESH_TOKEN", "")
    current_access = env.get("OPENCLAW_TWITCH_ACCESS_TOKEN", "")

    # Validate current token
    if current_access:
        info = validate_token(current_access, client_id)
        if info:
            expires_in = info.get("expires_in", 0)
            login = info.get("login", "unknown")
            print(f"Current token is VALID — user={login}, expires_in={expires_in}s ({expires_in // 60}m)")
            if args.check:
                sys.exit(0)
            if not args.force:
                print("Token is still valid. Use --force to refresh anyway.")
                sys.exit(0)
        else:
            print("Current access token is EXPIRED or INVALID.")
            if args.check:
                sys.exit(1)
    elif args.check:
        print("No access token found.")
        sys.exit(1)

    # Refresh
    print(f"Refreshing token with client_id={client_id[:8]}…")
    result = refresh_token(client_id, client_secret, current_refresh)

    new_access = result["access_token"]
    new_refresh = result.get("refresh_token", current_refresh)
    new_expires = result.get("expires_in", 0)
    now_ms = int(time.time() * 1000)

    updates = {
        "OPENCLAW_TWITCH_ACCESS_TOKEN": new_access,
        "OPENCLAW_TWITCH_REFRESH_TOKEN": new_refresh,
        "OPENCLAW_TWITCH_EXPIRES_IN": str(new_expires),
        "OPENCLAW_TWITCH_OBTAINMENT_TIMESTAMP": str(now_ms),
    }

    update_env(args.env_file, updates)

    rotated = "YES (rotated)" if new_refresh != current_refresh else "NO (same)"
    print(f"SUCCESS — new access token: {new_access[:8]}…{new_access[-4:]}")
    print(f"  expires_in: {new_expires}s ({new_expires // 3600}h)")
    print(f"  refresh token changed: {rotated}")
    print(f"  written to: {args.env_file}")
    print(f"\nRestart to pick up: docker compose up -d --force-recreate openclaw-gateway")


if __name__ == "__main__":
    main()
