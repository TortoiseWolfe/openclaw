#!/usr/bin/env python3
"""Tests for mcp_client.py — _resolve_url static method."""

import unittest

from mcp_client import MCPClient


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


if __name__ == "__main__":
    unittest.main()
