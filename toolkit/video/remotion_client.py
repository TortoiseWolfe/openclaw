#!/usr/bin/env python3
"""Remotion render service client.

Calls the remotion-renderer container to render video compositions.

Env vars:
  REMOTION_URL - Renderer base URL (default: http://remotion-renderer:3100)
"""

import json
import os
import sys
import urllib.request

REMOTION_URL = os.environ.get("REMOTION_URL", "http://remotion-renderer:3100")
TIMEOUT = 600  # 10 minutes for render (cold webpack bundles are slow)


def render(composition_id: str, props: dict, output_path: str) -> dict:
    """Render a composition to a video file.

    Args:
        composition_id: Remotion composition ID (e.g., 'SH-EpisodeOutro')
        props: Props to pass to the composition
        output_path: Output file path (inside /renders volume)

    Returns:
        dict with 'success' and 'outputPath' or 'error'
    """
    url = f"{REMOTION_URL}/render"
    data = json.dumps({
        "compositionId": composition_id,
        "props": props,
        "outputPath": output_path,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"success": False, "error": f"HTTP {e.code}: {body}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def health() -> bool:
    """Check if the renderer is healthy."""
    try:
        with urllib.request.urlopen(f"{REMOTION_URL}/health", timeout=5) as resp:
            data = json.loads(resp.read())
            return data.get("status") == "ok"
    except Exception:
        return False


def list_compositions() -> list[str]:
    """List available composition IDs."""
    try:
        with urllib.request.urlopen(f"{REMOTION_URL}/compositions", timeout=5) as resp:
            data = json.loads(resp.read())
            return data.get("compositions", [])
    except Exception:
        return []


# CLI usage
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: remotion_client.py <command> [args]")
        print("Commands:")
        print("  health              - Check renderer health")
        print("  list                - List compositions")
        print("  render <id> <props> <output> - Render a composition")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "health":
        ok = health()
        print(f"Renderer healthy: {ok}")
        sys.exit(0 if ok else 1)

    elif cmd == "list":
        comps = list_compositions()
        for c in comps:
            print(f"  {c}")

    elif cmd == "render":
        if len(sys.argv) < 5:
            print("Usage: remotion_client.py render <composition_id> <props_json> <output_path>")
            sys.exit(1)
        comp_id = sys.argv[2]
        props = json.loads(sys.argv[3])
        output = sys.argv[4]
        result = render(comp_id, props, output)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result.get("success") else 1)

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
