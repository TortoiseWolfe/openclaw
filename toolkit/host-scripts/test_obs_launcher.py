"""Tests for obs_launcher: auth, Host/Origin checks, status cache. No PowerShell."""

import http.client
import json
import secrets
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

import obs_launcher as ol


class LauncherTestBase(unittest.TestCase):
    token = ""

    def setUp(self):
        self.token = secrets.token_hex(16)
        self._patches = [
            mock.patch.object(ol, "_TOKEN", self.token),
            mock.patch.object(ol, "_is_obs_running", return_value=True),
            mock.patch.object(ol, "_launch_obs", return_value=True),
            mock.patch.object(ol, "_kill_obs", return_value=True),
        ]
        mocks = [p.start() for p in self._patches]
        self.running, self.launch, self.kill = mocks[1], mocks[2], mocks[3]
        ol._invalidate_cache()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ol.Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        for p in self._patches:
            p.stop()

    def req(self, method, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, headers=headers or {})
        resp = conn.getresponse()
        body = json.loads(resp.read() or b"{}")
        conn.close()
        return resp.status, body

    def auth(self):
        return {"Authorization": f"Bearer {self.token}"}


class TestLauncher(LauncherTestBase):
    def test_health_open(self):
        status, body = self.req("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_status_requires_token(self):
        status, _ = self.req("GET", "/status")
        self.assertEqual(status, 401)

    def test_status_wrong_token(self):
        status, _ = self.req("GET", "/status", {"Authorization": "Bearer wrong"})
        self.assertEqual(status, 401)

    def test_status_right_token(self):
        status, body = self.req("GET", "/status", self.auth())
        self.assertEqual(status, 200)
        self.assertEqual(body, {"running": True})

    def test_launch_with_token(self):
        status, body = self.req("POST", "/launch", self.auth())
        self.assertEqual(status, 200)
        self.assertEqual(body, {"launched": True, "running": True})
        self.launch.assert_called_once()

    def test_launch_without_token_does_not_launch(self):
        status, _ = self.req("POST", "/launch")
        self.assertEqual(status, 401)
        self.launch.assert_not_called()

    def test_kill_with_token(self):
        status, _ = self.req("POST", "/kill", self.auth())
        self.assertEqual(status, 200)
        self.kill.assert_called_once()

    def test_bad_host_rejected(self):
        status, _ = self.req("GET", "/health", {"Host": "evil.example"})
        self.assertEqual(status, 403)

    def test_allowed_hosts_with_port(self):
        for host in ("localhost:8100", "host.docker.internal:8100", "[::1]:8100"):
            status, _ = self.req("GET", "/health", {"Host": host})
            self.assertEqual(status, 200, host)

    def test_origin_rejected(self):
        status, _ = self.req("GET", "/health", {"Origin": "http://evil.example"})
        self.assertEqual(status, 403)
        status, _ = self.req("POST", "/launch", {**self.auth(), "Origin": "null"})
        self.assertEqual(status, 403)
        self.launch.assert_not_called()

    def test_token_unset_fails_closed(self):
        with mock.patch.object(ol, "_TOKEN", ""):
            status, body = self.req("GET", "/status", {"Authorization": "Bearer "})
            self.assertEqual(status, 503)
            self.assertEqual(body, {"error": "launcher auth not configured"})
            status, _ = self.req("GET", "/health")
            self.assertEqual(status, 200)

    def test_status_cached(self):
        self.req("GET", "/status", self.auth())
        self.req("GET", "/status", self.auth())
        self.assertEqual(self.running.call_count, 1)

    def test_launch_invalidates_cache(self):
        self.req("GET", "/status", self.auth())
        self.req("POST", "/launch", self.auth())
        self.running.reset_mock()
        self.req("GET", "/status", self.auth())
        self.assertEqual(self.running.call_count, 1)

    def test_log_line_sanitized(self):
        handler = ol.Handler.__new__(ol.Handler)
        with mock.patch.object(ol._log, "info") as info:
            handler.log_message("%s", "GET /a\r\n\x1b[31m" + "x" * 500)
        logged = info.call_args[0][1]
        self.assertNotIn("\n", logged)
        self.assertNotIn("\x1b", logged)
        self.assertLessEqual(len(logged), 200)


if __name__ == "__main__":
    unittest.main()
