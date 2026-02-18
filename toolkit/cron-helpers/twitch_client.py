#!/usr/bin/env python3
"""Lightweight Twitch Helix API helper.

Uses stdlib only (urllib.request) — no pip dependencies.

Env vars:
  OPENCLAW_TWITCH_ACCESS_TOKEN  - OAuth access token
  OPENCLAW_TWITCH_CLIENT_ID     - Twitch application client ID
"""

import json
import os
import sys
import urllib.error
import urllib.request

HELIX_BASE = "https://api.twitch.tv/helix"


def _headers() -> dict[str, str]:
    token = os.environ.get("OPENCLAW_TWITCH_ACCESS_TOKEN", "")
    client_id = os.environ.get("OPENCLAW_TWITCH_CLIENT_ID", "")
    if not token or not client_id:
        print("ERROR: OPENCLAW_TWITCH_ACCESS_TOKEN and OPENCLAW_TWITCH_CLIENT_ID required",
              file=sys.stderr)
        sys.exit(1)
    return {
        "Authorization": f"Bearer {token}",
        "Client-Id": client_id,
        "Content-Type": "application/json",
    }


def _helix_get(path: str) -> dict:
    url = f"{HELIX_BASE}{path}"
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"Helix GET {path} failed ({e.code}): {body}", file=sys.stderr)
        raise


def _helix_patch(path: str, body: dict) -> None:
    url = f"{HELIX_BASE}{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=_headers(), method="PATCH")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            _ = resp.read()
    except urllib.error.HTTPError as e:
        resp_body = e.read().decode("utf-8", errors="replace")
        print(f"Helix PATCH {path} failed ({e.code}): {resp_body}", file=sys.stderr)
        raise


def get_broadcaster_id() -> str:
    """Get the broadcaster ID for the authenticated user."""
    data = _helix_get("/users")
    users = data.get("data", [])
    if not users:
        print("ERROR: No user data returned from /users", file=sys.stderr)
        sys.exit(1)
    return users[0]["id"]


def get_game_id(game_name: str) -> str | None:
    """Resolve a game/category name to its Twitch ID."""
    encoded = urllib.request.quote(game_name)
    data = _helix_get(f"/games?name={encoded}")
    games = data.get("data", [])
    return games[0]["id"] if games else None


def update_channel(title: str | None = None, game: str | None = None) -> None:
    """Update Twitch channel title and/or game category.

    Args:
        title: New stream title (None to leave unchanged).
        game: Game/category name to set (None to leave unchanged).
    """
    if not title and not game:
        return

    broadcaster_id = get_broadcaster_id()
    body: dict = {}

    if title:
        body["title"] = title
        print(f"Setting Twitch title: {title}")

    if game:
        game_id = get_game_id(game)
        if game_id:
            body["game_id"] = game_id
            print(f"Setting Twitch category: {game} (id={game_id})")
        else:
            print(f"WARNING: Game '{game}' not found on Twitch, skipping category update",
                  file=sys.stderr)

    if body:
        _helix_patch(f"/channels?broadcaster_id={broadcaster_id}", body)
        print("Twitch channel updated")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Update Twitch channel metadata")
    parser.add_argument("--title", help="Set stream title")
    parser.add_argument("--category", help="Set game/category name")
    args = parser.parse_args()

    if not args.title and not args.category:
        parser.error("At least one of --title or --category is required")

    update_channel(title=args.title, game=args.category)


if __name__ == "__main__":
    main()
