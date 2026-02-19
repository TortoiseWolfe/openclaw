#!/usr/bin/env python3
"""Minimal MCP-over-SSE client using only stdlib.

Connects to the Docker MCP Gateway via SSE, completes the initialization
handshake, and provides a call_tool() method for JSON-RPC tool invocations.

Usage:
    from mcp_client import MCPClient

    with MCPClient() as mcp:
        result = mcp.call_tool("search_jobs", {"search_term": "React developer"})
        jobs = json.loads(result)  # list of job dicts
"""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

# Default config path inside Docker container
DEFAULT_CONFIG = "/home/node/.openclaw/config/mcporter.json"


class MCPError(Exception):
    """Raised when an MCP protocol operation fails."""


class MCPClient:
    """Minimal MCP-over-SSE client (stdlib only)."""

    def __init__(self, config_path=DEFAULT_CONFIG, connect_timeout=30,
                 read_timeout=120):
        self._config_path = config_path
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._sse_conn = None
        self._endpoint = None
        self._auth = None
        self._req_id = 0

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    def connect(self):
        """Connect to MCP gateway, discover endpoint, initialize session."""
        base_url, self._auth = self._load_config()
        self._sse_conn, self._endpoint = self._connect_sse(base_url)
        try:
            self._initialize()
        except Exception:
            self.close()
            raise

    def close(self):
        """Close the SSE connection."""
        if self._sse_conn:
            try:
                self._sse_conn.close()
            except Exception:
                pass
            self._sse_conn = None

    def call_tool(self, name, arguments, timeout_seconds=None):
        """Call an MCP tool and return the text result.

        Returns the text content from the tool response.
        Raises MCPError if the tool returns an error or times out.
        """
        self._req_id += 1
        req_id = self._req_id

        self._post_jsonrpc("tools/call", {
            "name": name,
            "arguments": arguments,
        }, req_id)

        if timeout_seconds and self._sse_conn:
            try:
                self._sse_conn.fp.raw._sock.settimeout(timeout_seconds)
            except Exception:
                pass

        resp = self._read_response(req_id)

        if timeout_seconds and self._sse_conn:
            try:
                self._sse_conn.fp.raw._sock.settimeout(self._read_timeout)
            except Exception:
                pass

        if not resp:
            raise MCPError(f"No response for {name}")

        if "error" in resp:
            msg = resp["error"].get("message", str(resp["error"]))
            raise MCPError(f"Tool {name} error: {msg}")

        # Extract text content from result
        result = resp.get("result", {})
        if result.get("isError"):
            content = result.get("content", [{}])
            msg = content[0].get("text", "Unknown error") if content else "Unknown error"
            raise MCPError(f"Tool {name} returned error: {msg}")

        content = result.get("content", [])
        texts = [c["text"] for c in content if c.get("type") == "text"]
        return "\n".join(texts)

    # ── Internal methods ────────────────────────────────────────────

    def _load_config(self):
        """Load MCP gateway URL and auth from mcporter.json."""
        with open(self._config_path) as f:
            config = json.load(f)
        server = config["mcpServers"]["docker-mcp"]
        base_url = server["baseUrl"]
        auth = server["headers"].get("Authorization", "")
        if not auth or auth == "Bearer " or auth.strip() == "Bearer":
            raise ValueError(
                "MCP gateway auth token is empty or missing in mcporter.json. "
                "Set headers.Authorization to 'Bearer <token>'."
            )
        return base_url, auth

    def _connect_sse(self, base_url):
        """Connect to SSE endpoint and discover the session URL."""
        req = Request(base_url, headers={
            "Authorization": self._auth,
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
        })
        resp = urlopen(req, timeout=self._connect_timeout)

        # Extend socket timeout for tool responses. If the SSE connection
        # drops mid-stream, readline() will block until this timeout expires.
        # Cron job timeoutSeconds (300s) acts as the outer safety net.
        try:
            resp.fp.raw._sock.settimeout(self._read_timeout)
        except Exception:
            pass

        # Read SSE events to find endpoint
        event_type = None
        for _ in range(50):
            line = resp.readline().decode("utf-8").rstrip("\n")
            if not line:
                continue
            if line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: ") and event_type == "endpoint":
                data = line[6:]
                try:
                    parsed = json.loads(data)
                    endpoint = parsed if isinstance(parsed, str) else parsed.get("endpoint", data)
                except json.JSONDecodeError:
                    endpoint = data.strip()
                endpoint = self._resolve_url(base_url, endpoint)
                return resp, endpoint

        resp.close()
        raise MCPError("Could not discover endpoint from SSE stream")

    def _initialize(self):
        """Complete MCP initialization handshake."""
        self._post_jsonrpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "openclaw-python", "version": "0.1.0"},
        }, "init-1")

        resp = self._read_response("init-1")
        if not resp or "error" in resp:
            raise MCPError(f"Initialization failed: {resp}")

        # Send initialized notification (fire-and-forget)
        payload = json.dumps({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }).encode()
        headers = {"Content-Type": "application/json", "Authorization": self._auth}
        self._post(self._endpoint, payload, headers)

    def _post_jsonrpc(self, method, params, req_id):
        """Send a JSON-RPC request."""
        payload = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": req_id,
        }).encode()
        headers = {"Content-Type": "application/json", "Authorization": self._auth}
        self._post(self._endpoint, payload, headers)

    def _post(self, url, payload, headers, max_redirects=3):
        """POST with manual redirect following.

        Auth headers are only forwarded to redirects on the same origin
        to prevent bearer token leakage to third-party hosts.
        """
        original_origin = urlparse(url).netloc
        for _ in range(max_redirects):
            req = Request(url, data=payload, headers=headers)
            try:
                urlopen(req, timeout=30).read()
                return
            except HTTPError as e:
                if e.code in (301, 302, 307, 308):
                    location = e.headers.get("Location", "")
                    if location:
                        url = self._resolve_url(url, location)
                        # Strip auth header if redirected to a different origin
                        if urlparse(url).netloc != original_origin:
                            headers = {k: v for k, v in headers.items()
                                       if k.lower() != "authorization"}
                        continue
                if 200 <= e.code < 300:
                    return  # 202 Accepted etc.
                raise
        raise MCPError("Too many redirects")

    def _read_response(self, expected_id, max_lines=200):
        """Read SSE stream until we get a matching JSON-RPC response."""
        for _ in range(max_lines):
            try:
                line = self._sse_conn.readline().decode("utf-8").rstrip("\n")
            except Exception:
                return None
            if not line or line.startswith("event: "):
                continue
            if line.startswith("data: "):
                try:
                    parsed = json.loads(line[6:])
                    if ("result" in parsed or "error" in parsed) and \
                       parsed.get("id") == expected_id:
                        return parsed
                except json.JSONDecodeError:
                    pass
        return None

    @staticmethod
    def _resolve_url(base, url):
        """Resolve a potentially relative URL against a base URL."""
        if url.startswith("http://") or url.startswith("https://"):
            return url
        parsed = urlparse(base)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        return origin + ("" if url.startswith("/") else "/") + url
