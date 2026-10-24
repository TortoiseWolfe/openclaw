#!/usr/bin/env python3
"""Tests for obs_client CLI argument checks and launcher auth."""

import json
import os
import unittest
from unittest import mock

import obs_client


class TestBrowserUrlCheck(unittest.TestCase):
    def test_allowed(self):
        for url in ("http://localhost:3100/game/crawl.html",
                    "http://remotion-renderer:3100/x",
                    "https://127.0.0.1/x",
                    "http://host.docker.internal:3100/"):
            obs_client._cli_check_browser_url(url)

    def test_rejected(self):
        for url in ("http://evil.example/x", "file:///etc/passwd", "javascript:alert(1)",
                    "http://localhost.evil.example/", "ftp://localhost/", "http://user@evil.example/"):
            with self.assertRaises(SystemExit) as cm:
                obs_client._cli_check_browser_url(url)
            self.assertEqual(cm.exception.code, 2, url)


class TestMediaPathCheck(unittest.TestCase):
    def test_renders_path_ok(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OBS_RENDERS_WIN_PREFIX", None)
            obs_client._cli_check_media_path(obs_client.RENDERS_DIR + "/docker/ep/content-1.mp4")

    def test_outside_rejected(self):
        for p in ("/etc/passwd", obs_client.RENDERS_DIR + "/../secrets.mp4", "C:\\Windows\\x.mp4"):
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("OBS_RENDERS_WIN_PREFIX", None)
                with self.assertRaises(SystemExit) as cm:
                    obs_client._cli_check_media_path(p)
                self.assertEqual(cm.exception.code, 2, p)

    def test_windows_prefix_ok_when_set(self):
        prefix = "\\\\wsl$\\Ubuntu\\renders"
        with mock.patch.dict(os.environ, {"OBS_RENDERS_WIN_PREFIX": prefix}):
            obs_client._cli_check_media_path(prefix + "\\ep\\content.mp4")
            with self.assertRaises(SystemExit):
                obs_client._cli_check_media_path("C:\\other\\x.mp4")


class TestParserDifferentials(unittest.TestCase):
    """Values OBS (Chromium / Win32) would read differently from Python must be refused."""

    def test_browser_url_authority_tricks(self):
        for url in ("http://evil.example\\@localhost/", "http://evil.example\\.localhost/",
                    "http://localhost@evil.example/", "http://local host/", "http://localhost\t/",
                    "http://localhost:3100/\\..\\x", " http://localhost/", "http://localhost/\n"):
            with self.assertRaises(SystemExit, msg=repr(url)):
                obs_client._cli_check_browser_url(url)

    def test_windows_prefix_lookalike_and_trailing_dots(self):
        prefix = "C:\\Users\\x\\renders"
        bad = (prefix + "-evil\\a.mp4", prefix + "\\.. \\a.mp4", prefix + "\\...\\a.mp4",
               prefix + "\\a.mp4:stream", prefix + "\\..\\a.mp4", prefix + "\\ep.\\a.mp4",
               prefix + "/../a.mp4")
        with mock.patch.dict(os.environ, {"OBS_RENDERS_WIN_PREFIX": prefix}):
            obs_client._cli_check_media_path(prefix + "\\docker\\ep\\content-1.mp4")
            for p in bad:
                with self.assertRaises(SystemExit, msg=repr(p)):
                    obs_client._cli_check_media_path(p)

    def test_container_path_with_backslashes(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OBS_RENDERS_WIN_PREFIX", None)
            for p in (obs_client.RENDERS_DIR + "/..\\..\\Windows\\x.mp4",
                      obs_client.RENDERS_DIR + "/ep/a b.mp4", obs_client.RENDERS_DIR + "/ep/:x.mp4", obs_client.RENDERS_DIR + "/ep/a.mp4\n",
                      obs_client.RENDERS_DIR + "-evil/a.mp4"):
                with self.assertRaises(SystemExit, msg=repr(p)):
                    obs_client._cli_check_media_path(p)


class TestLauncherAuth(unittest.TestCase):
    def _call(self, fn, env):
        resp = mock.Mock()
        resp.read.return_value = json.dumps({"running": True}).encode()
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch("urllib.request.urlopen", return_value=resp) as uo:
            if "OBS_LAUNCHER_TOKEN" not in env:
                os.environ.pop("OBS_LAUNCHER_TOKEN", None)
            fn()
        return uo.call_args[0][0]

    def test_header_sent_when_token_set(self):
        token = "tok-" + "y" * 20
        env = {"OBS_LAUNCHER_TOKEN": token}
        for fn in (lambda: obs_client.launch_obs(wait=False), obs_client.kill_obs, obs_client.launcher_status):
            req = self._call(fn, env)
            self.assertEqual(req.get_header("Authorization"), f"Bearer {token}")

    def test_no_header_without_token(self):
        for fn in (lambda: obs_client.launch_obs(wait=False), obs_client.kill_obs, obs_client.launcher_status):
            req = self._call(fn, {})
            self.assertIsNone(req.get_header("Authorization"))


if __name__ == "__main__":
    unittest.main()
