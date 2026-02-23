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
import time
import urllib.error
import urllib.request

HELIX_BASE = "https://api.twitch.tv/helix"


_DOT_ENV_PATH = os.path.join(
    os.environ.get("HOME", "/home/node"), ".openclaw", ".env",
)


def _load_token_from_dotenv(key: str) -> str:
    """Read a token from ~/.openclaw/.env (picks up refreshed tokens)."""
    try:
        with open(_DOT_ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    except FileNotFoundError:
        pass
    return ""


def _headers() -> dict[str, str]:
    # Prefer fresh tokens from .env (handles mid-session token refresh)
    token = _load_token_from_dotenv("OPENCLAW_TWITCH_ACCESS_TOKEN") or os.environ.get("OPENCLAW_TWITCH_ACCESS_TOKEN", "")
    client_id = _load_token_from_dotenv("OPENCLAW_TWITCH_CLIENT_ID") or os.environ.get("OPENCLAW_TWITCH_CLIENT_ID", "")
    if not token or not client_id:
        print("ERROR: OPENCLAW_TWITCH_ACCESS_TOKEN and OPENCLAW_TWITCH_CLIENT_ID required",
              file=sys.stderr)
        sys.exit(1)
    return {
        "Authorization": f"Bearer {token}",
        "Client-Id": client_id,
        "Content-Type": "application/json",
    }


def _raw_helix_get(path: str) -> dict:
    url = f"{HELIX_BASE}{path}"
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"Helix GET {path} failed ({e.code}): {body}", file=sys.stderr)
        raise


def _raw_helix_post(path: str, body: dict) -> dict:
    url = f"{HELIX_BASE}{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        resp_body = e.read().decode("utf-8", errors="replace")
        print(f"Helix POST {path} failed ({e.code}): {resp_body}", file=sys.stderr)
        raise


def _raw_helix_patch(path: str, body: dict) -> None:
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


_broadcaster_id_cache: str | None = None
_refresh_attempted = False


def _try_refresh_token() -> bool:
    """Attempt to refresh the Twitch access token. Returns True on success."""
    global _refresh_attempted, _broadcaster_id_cache
    if _refresh_attempted:
        return False
    _refresh_attempted = True
    try:
        from twitch_token_refresh import refresh_token, update_env, read_env, DOT_ENV_PATH
        env = read_env(DOT_ENV_PATH)
        client_id = env.get("OPENCLAW_TWITCH_CLIENT_ID", "")
        client_secret = env.get("OPENCLAW_TWITCH_CLIENT_SECRET", "")
        refresh_tok = env.get("OPENCLAW_TWITCH_REFRESH_TOKEN", "")
        if not all([client_id, client_secret, refresh_tok]):
            print("Token refresh skipped — missing credentials", file=sys.stderr)
            return False
        result = refresh_token(client_id, client_secret, refresh_tok)
        updates = {
            "OPENCLAW_TWITCH_ACCESS_TOKEN": result["access_token"],
            "OPENCLAW_TWITCH_REFRESH_TOKEN": result.get("refresh_token", refresh_tok),
            "OPENCLAW_TWITCH_EXPIRES_IN": str(result.get("expires_in", 0)),
            "OPENCLAW_TWITCH_OBTAINMENT_TIMESTAMP": str(int(time.time() * 1000)),
        }
        update_env(DOT_ENV_PATH, updates)
        _broadcaster_id_cache = None
        print(f"Token auto-refreshed (expires in {result.get('expires_in', '?')}s)", file=sys.stderr)
        return True
    except SystemExit:
        raise  # Let sys.exit() propagate (dead refresh token)
    except Exception as e:
        print(f"Token auto-refresh failed: {e}", file=sys.stderr)
        return False


def _retry_on_dns(fn, *args, retries: int = 2):
    """Retry a callable on transient DNS errors (URLError)."""
    for attempt in range(retries + 1):
        try:
            return fn(*args)
        except urllib.error.URLError as e:
            if "Name or service not known" in str(e) and attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise


def _helix_get(path: str) -> dict:
    """Helix GET with auto-refresh on 401 and DNS retry."""
    global _refresh_attempted
    try:
        result = _retry_on_dns(_raw_helix_get, path)
        _refresh_attempted = False
        return result
    except urllib.error.HTTPError as e:
        if e.code != 401 or not _try_refresh_token():
            raise
        result = _raw_helix_get(path)
        _refresh_attempted = False
        return result


def _helix_post(path: str, body: dict) -> dict:
    """Helix POST with auto-refresh on 401 and DNS retry."""
    global _refresh_attempted
    try:
        result = _retry_on_dns(_raw_helix_post, path, body)
        _refresh_attempted = False
        return result
    except urllib.error.HTTPError as e:
        if e.code != 401 or not _try_refresh_token():
            raise
        result = _raw_helix_post(path, body)
        _refresh_attempted = False
        return result


def _helix_patch(path: str, body: dict) -> None:
    """Helix PATCH with auto-refresh on 401 and DNS retry."""
    global _refresh_attempted
    try:
        _retry_on_dns(_raw_helix_patch, path, body)
        _refresh_attempted = False
    except urllib.error.HTTPError as e:
        if e.code != 401 or not _try_refresh_token():
            raise
        _raw_helix_patch(path, body)
        _refresh_attempted = False


def get_broadcaster_id() -> str:
    """Get the broadcaster ID for the authenticated user (cached)."""
    global _broadcaster_id_cache
    if _broadcaster_id_cache is not None:
        return _broadcaster_id_cache
    data = _helix_get("/users")
    users = data.get("data", [])
    if not users:
        print("ERROR: No user data returned from /users", file=sys.stderr)
        sys.exit(1)
    _broadcaster_id_cache = users[0]["id"]
    return _broadcaster_id_cache


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


def send_chat_message(message: str) -> None:
    """Send a message to the broadcaster's Twitch chat.

    Uses Helix POST /chat/messages. Requires user:write:chat scope.
    Messages over 500 chars are truncated (Twitch limit).
    Returns silently if tokens are not configured.
    """
    if not message or message == "(no narration)":
        return
    token = _load_token_from_dotenv("OPENCLAW_TWITCH_ACCESS_TOKEN") or os.environ.get("OPENCLAW_TWITCH_ACCESS_TOKEN", "")
    client_id = _load_token_from_dotenv("OPENCLAW_TWITCH_CLIENT_ID") or os.environ.get("OPENCLAW_TWITCH_CLIENT_ID", "")
    if not token or not client_id:
        return
    broadcaster_id = get_broadcaster_id()
    truncated = message[:500]
    _helix_post("/chat/messages", {
        "broadcaster_id": broadcaster_id,
        "sender_id": broadcaster_id,
        "message": truncated,
    })


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
