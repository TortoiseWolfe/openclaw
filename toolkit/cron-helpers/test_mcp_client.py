#!/usr/bin/env python3
"""Tests for mcp_client.py — _resolve_url static method."""

import io
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request

import mcp_client
from mcp_client import ALLOWED_TOOLS, MCPClient, MCPError


class TestResolveUrl(unittest.TestCase):
    def test_absolute_http_returned_unchanged(self):
        result = MCPClient._resolve_url(
            "http://mcp-gateway:8808/sse",
            "http://other-host:9000/path",
        )
        self.assertEqual(result, "http://other-host:9000/path")

    def test_absolute_https_returned_unchanged(self):
        result = MCPClient._resolve_url(
            "http://mcp-gateway:8808/sse",
            "https://secure.example.com/endpoint",
        )
        self.assertEqual(result, "https://secure.example.com/endpoint")

    def test_relative_path_with_leading_slash(self):
        result = MCPClient._resolve_url(
            "http://mcp-gateway:8808/sse",
            "/messages?sessionId=abc123",
        )
        self.assertEqual(result, "http://mcp-gateway:8808/messages?sessionId=abc123")

    def test_relative_path_without_leading_slash(self):
        result = MCPClient._resolve_url(
            "http://mcp-gateway:8808/sse",
            "messages?sessionId=abc123",
        )
        self.assertEqual(result, "http://mcp-gateway:8808/messages?sessionId=abc123")

    def test_preserves_port_in_origin(self):
        result = MCPClient._resolve_url(
            "http://localhost:3000/api/sse",
            "/endpoint",
        )
        self.assertEqual(result, "http://localhost:3000/endpoint")


class TestNoRedirect(unittest.TestCase):
    def test_handler_raises_on_every_3xx(self):
        handler = mcp_client._NoRedirect()
        req = Request("http://mcp-gateway:8808/sse", headers={"Authorization": "Bearer x"})
        for code in (301, 302, 303, 307, 308):
            with self.assertRaises(MCPError, msg=str(code)):
                handler.redirect_request(req, None, code, "Moved", {}, "http://evil.example/")

    def test_urlopen_uses_no_redirect_opener(self):
        with mock.patch.object(mcp_client, "_opener") as opener:
            mcp_client.urlopen("REQ", timeout=5)
        opener.open.assert_called_once_with("REQ", timeout=5)

    def test_post_3xx_raises_mcp_error(self):
        client = MCPClient()
        err = HTTPError("http://mcp-gateway:8808/m", 302, "Found", {"Location": "http://evil/"}, io.BytesIO())
        with mock.patch.object(mcp_client, "urlopen", side_effect=err) as uo:
            with self.assertRaises(MCPError):
                client._post("http://mcp-gateway:8808/m", b"{}", {"Authorization": "Bearer x"})
        self.assertEqual(uo.call_count, 1)

    def test_post_202_ok(self):
        client = MCPClient()
        err = HTTPError("http://mcp-gateway:8808/m", 202, "Accepted", {}, io.BytesIO())
        with mock.patch.object(mcp_client, "urlopen", side_effect=err):
            client._post("http://mcp-gateway:8808/m", b"{}", {})


class _FakeSSE:
    def __init__(self, lines):
        self._lines = [l.encode() + b"\n" for l in lines]
        self.closed = False
        self.fp = None

    def readline(self):
        return self._lines.pop(0) if self._lines else b""

    def close(self):
        self.closed = True


class TestEndpointOrigin(unittest.TestCase):
    def _connect(self, endpoint):
        client = MCPClient(config_path="unused")
        client._auth = "Bearer " + "x" * 20
        fake = _FakeSSE(["event: endpoint", "data: " + endpoint])
        with mock.patch.object(mcp_client, "urlopen", return_value=fake):
            return client._connect_sse("http://mcp-gateway:8808/sse"), fake

    def test_relative_endpoint_ok(self):
        (conn, ep), _ = self._connect("/messages?sessionId=1")
        self.assertEqual(ep, "http://mcp-gateway:8808/messages?sessionId=1")

    def test_same_origin_absolute_ok(self):
        (_, ep), _ = self._connect("http://mcp-gateway:8808/m")
        self.assertEqual(ep, "http://mcp-gateway:8808/m")

    def test_other_host_rejected(self):
        with self.assertRaises(MCPError):
            self._connect("http://evil.example:8808/m")

    def test_other_port_rejected(self):
        with self.assertRaises(MCPError):
            self._connect("http://mcp-gateway:9999/m")

    def test_other_scheme_rejected(self):
        with self.assertRaises(MCPError):
            self._connect("https://mcp-gateway:8808/m")


class TestAllowedTools(unittest.TestCase):
    def test_known_tools(self):
        self.assertIn("search_jobs", ALLOWED_TOOLS)
        self.assertIn("browser_navigate", ALLOWED_TOOLS)

    def test_unknown_tool_rejected_before_any_request(self):
        client = MCPClient()
        with mock.patch.object(client, "_post_jsonrpc") as post:
            with self.assertRaises(ValueError):
                client.call_tool("browser_evaluate", {})
        post.assert_not_called()

    def test_allowed_tool_proceeds(self):
        client = MCPClient()
        resp = {"result": {"content": [{"type": "text", "text": "ok"}]}}
        with mock.patch.object(client, "_post_jsonrpc"), \
             mock.patch.object(client, "_read_response", return_value=resp):
            self.assertEqual(client.call_tool("search_jobs", {}), "ok")


if __name__ == "__main__":
    unittest.main()
