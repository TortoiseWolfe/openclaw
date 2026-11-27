#!/usr/bin/env python3
"""Tests for remotion_client.render auth header."""

import io
import json
import os
import unittest
from unittest import mock

import remotion_client


def _fake_response():
    return io.BytesIO(json.dumps({"success": True}).encode())


class TestRenderAuth(unittest.TestCase):
    def _render(self, env):
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch("urllib.request.urlopen", return_value=_fake_response()) as uo:
            os.environ.pop("RENDERER_TOKEN", None) if "RENDERER_TOKEN" not in env else None
            result = remotion_client.render("Comp", {}, "/renders/x.mp4")
        self.assertTrue(result["success"])
        return uo.call_args[0][0]

    def test_token_sent_when_set(self):
        token = "tok-" + "x" * 20
        req = self._render({"RENDERER_TOKEN": token})
        self.assertEqual(req.get_header("Authorization"), f"Bearer {token}")
        self.assertEqual(req.get_header("Content-type"), "application/json")

    def test_no_header_without_token(self):
        req = self._render({})
        self.assertIsNone(req.get_header("Authorization"))
        self.assertEqual(req.get_header("Content-type"), "application/json")


if __name__ == "__main__":
    unittest.main()
