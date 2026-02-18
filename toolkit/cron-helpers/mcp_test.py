#!/usr/bin/env python3
"""Minimal MCP-over-SSE connectivity test.

Connects to the MCP gateway, discovers the endpoint, and calls search_jobs
with a test query to verify the protocol works from Python.
"""

import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

# Config path inside Docker container
CONFIG_PATH = "/home/node/.clawdbot/config/mcporter.json"


def load_config():
    """Load MCP gateway config."""
    with open(CONFIG_PATH) as f:
        config = json.load(f)
    server = config["mcpServers"]["docker-mcp"]
    base_url = server["baseUrl"]
    auth_header = server["headers"].get("Authorization", "")
    return base_url, auth_header


def _resolve_endpoint(base_url, endpoint):
    """Resolve a potentially relative endpoint URL against the base URL."""
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        return endpoint
    # Relative path — combine with base URL origin
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if endpoint.startswith("/"):
        return origin + endpoint
    return origin + "/" + endpoint


def connect_sse(base_url, auth_header):
    """Connect to SSE endpoint and extract the session endpoint URL."""
    print(f"Connecting to {base_url}...")
    req = Request(base_url, headers={
        "Authorization": auth_header,
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache",
    })
    # Short timeout for initial connect; we'll extend it later for tool responses
    resp = urlopen(req, timeout=30)
    print(f"Connected. Status: {resp.status}")
    # Extend socket timeout for long-running tool calls (LinkedIn can take 60s+)
    try:
        resp.fp.raw._sock.settimeout(120)
    except Exception:
        pass  # not critical if this fails

    # Read SSE events to find the endpoint
    endpoint = None
    event_type = None
    lines_read = 0

    while lines_read < 50:  # safety limit
        line = resp.readline().decode("utf-8").rstrip("\n")
        lines_read += 1

        if not line:
            continue  # empty line = event boundary

        if line.startswith("event: "):
            event_type = line[7:]
            print(f"  SSE event type: {event_type}")
        elif line.startswith("data: "):
            data = line[6:]
            print(f"  SSE data: {data[:200]}")

            # Extract endpoint from SSE event
            if event_type == "endpoint":
                # Data could be raw path, JSON string, or JSON object
                try:
                    parsed = json.loads(data)
                    if isinstance(parsed, str):
                        endpoint = parsed
                    elif isinstance(parsed, dict) and "endpoint" in parsed:
                        endpoint = parsed["endpoint"]
                except json.JSONDecodeError:
                    # Raw text — use as-is (may be relative path)
                    endpoint = data.strip()

            if endpoint:
                endpoint = _resolve_endpoint(base_url, endpoint)
                print(f"\nEndpoint discovered: {endpoint}")
                return resp, endpoint

    print("ERROR: Could not discover endpoint after 50 lines", file=sys.stderr)
    resp.close()
    sys.exit(1)


def _get_message_url(endpoint):
    """Derive the POST message URL from the SSE endpoint URL.

    MCP-over-SSE convention: POST to /message with the same sessionid query param.
    """
    parsed = urlparse(endpoint)
    message_path = parsed.path.replace("/sse", "/message") if "/sse" in parsed.path else "/message"
    return f"{parsed.scheme}://{parsed.netloc}{message_path}?{parsed.query}" if parsed.query else f"{parsed.scheme}://{parsed.netloc}{message_path}"


def _post_with_redirect(url, payload, headers, max_redirects=3):
    """POST with manual redirect following (urllib doesn't follow POST redirects)."""
    for _ in range(max_redirects):
        req = Request(url, data=payload, headers=headers)
        try:
            resp = urlopen(req, timeout=30)
            body = resp.read().decode()
            return resp.status, body, None
        except HTTPError as e:
            if e.code in (301, 302, 307, 308):
                location = e.headers.get("Location", "")
                if location:
                    # Resolve relative redirects
                    if not location.startswith("http"):
                        parsed = urlparse(url)
                        location = f"{parsed.scheme}://{parsed.netloc}{location}"
                    print(f"  Following {e.code} redirect → {location}")
                    url = location
                    continue
            body = e.read().decode()
            return e.code, body, None
        except URLError as e:
            return None, None, str(e)
    return None, None, "Too many redirects"


def _post_jsonrpc(endpoint, auth_header, method, params, req_id):
    """Send a JSON-RPC request to the MCP endpoint."""
    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": req_id,
    }).encode()

    headers = {
        "Content-Type": "application/json",
        "Authorization": auth_header,
    }

    status, body, err = _post_with_redirect(endpoint, payload, headers)
    if err:
        print(f"  POST error: {err}")
    elif status:
        print(f"  POST {method} → {status}")
    return status, body


def _read_sse_response(sse_conn, expected_id=None, max_lines=200):
    """Read SSE stream until we get a JSON-RPC response matching expected_id."""
    lines_read = 0
    while lines_read < max_lines:
        try:
            line = sse_conn.readline().decode("utf-8").rstrip("\n")
        except Exception as e:
            print(f"  SSE read error: {e}")
            return None
        lines_read += 1

        if not line:
            continue

        if line.startswith("event: "):
            pass  # skip event type lines
        elif line.startswith("data: "):
            data = line[6:]
            try:
                parsed = json.loads(data)
                if "result" in parsed or "error" in parsed:
                    if expected_id is None or parsed.get("id") == expected_id:
                        return parsed
            except json.JSONDecodeError:
                pass

    return None


def initialize(sse_conn, endpoint, auth_header):
    """Complete the MCP initialization handshake."""
    print("\n--- MCP Initialization ---")

    # Step 1: Send initialize request
    print("Sending initialize...")
    _post_jsonrpc(endpoint, auth_header, "initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "mcp-test", "version": "0.1.0"},
    }, req_id="init-1")

    # Step 2: Read initialize response
    resp = _read_sse_response(sse_conn, expected_id="init-1")
    if resp and "result" in resp:
        server_info = resp["result"].get("serverInfo", {})
        print(f"  Server: {server_info.get('name', '?')} v{server_info.get('version', '?')}")
        print(f"  Protocol: {resp['result'].get('protocolVersion', '?')}")
    elif resp and "error" in resp:
        print(f"  Init error: {resp['error']}")
        return False
    else:
        print("  No init response received")
        return False

    # Step 3: Send initialized notification (no id, no response expected)
    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    }).encode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": auth_header,
    }
    _post_with_redirect(endpoint, payload, headers)
    print("  Sent initialized notification")
    print("--- Initialization complete ---\n")
    return True


def call_tool(sse_conn, endpoint, auth_header, tool_name, arguments):
    """Call an MCP tool via JSON-RPC POST."""
    print(f"Calling tool: {tool_name}({json.dumps(arguments)})")

    _post_jsonrpc(endpoint, auth_header, "tools/call", {
        "name": tool_name,
        "arguments": arguments,
    }, req_id=1)

    # Read response from SSE stream
    print("Reading SSE response...")
    resp = _read_sse_response(sse_conn, expected_id=1, max_lines=200)
    if resp:
        print(f"\nTool response received!")
        print(json.dumps(resp, indent=2)[:2000])
    else:
        print("WARNING: No tool response received")
    return resp


def main():
    print("=== MCP Gateway Connectivity Test ===\n")

    # Load config
    try:
        base_url, auth_header = load_config()
        print(f"Config loaded. Gateway: {base_url}")
        print(f"Auth: {auth_header[:20]}...")
    except Exception as e:
        print(f"ERROR loading config: {e}", file=sys.stderr)
        sys.exit(1)

    # Connect to SSE
    try:
        sse_conn, endpoint = connect_sse(base_url, auth_header)
    except (HTTPError, URLError) as e:
        print(f"ERROR connecting to SSE: {e}", file=sys.stderr)
        sys.exit(1)

    # Initialize MCP session
    try:
        if not initialize(sse_conn, endpoint, auth_header):
            print("ERROR: MCP initialization failed", file=sys.stderr)
            sse_conn.close()
            sys.exit(1)
    except Exception as e:
        print(f"ERROR during initialization: {e}", file=sys.stderr)
        sse_conn.close()
        sys.exit(1)

    # Call search_jobs with a minimal test query
    try:
        result = call_tool(sse_conn, endpoint, auth_header,
                          "search_jobs", {"search_term": "software developer test"})
        if result and "result" in result:
            print("\n=== SUCCESS: MCP gateway is reachable from Python ===")
        elif result and "error" in result:
            print(f"\n=== TOOL ERROR: {result['error'].get('message', 'unknown')} ===")
        else:
            print("\n=== PARTIAL: Connected but no tool response ===")
    except Exception as e:
        print(f"\nERROR calling tool: {e}", file=sys.stderr)
    finally:
        sse_conn.close()


if __name__ == "__main__":
    main()
