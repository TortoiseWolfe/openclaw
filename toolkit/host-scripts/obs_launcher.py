#!/usr/bin/env python3
"""Minimal HTTP server for launching OBS from WSL2.

Run this on the WSL2 host (outside Docker):
  python3 obs_launcher.py
  python3 obs_launcher.py --port 8100
  python3 obs_launcher.py --obs-path 'C:\\Program Files\\obs-studio\\bin\\64bit\\obs64.exe'

OpenClaw inside Docker calls this to start/stop OBS on the Windows host.
"""

import argparse
import hmac
import json
import logging
import logging.handlers
import ntpath
import os
import re
import subprocess
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

DEFAULT_PORT = 8100
DEFAULT_OBS_PATH = r"C:\Program Files\obs-studio\bin\64bit\obs64.exe"

ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "host.docker.internal"})
STATUS_CACHE_TTL = 5.0

# Bearer token, loaded from OBS_LAUNCHER_TOKEN at startup. Empty = fail closed.
_TOKEN = ""

_START_TIME = time.time()
_cache_lock = threading.Lock()
_cache_value = False
_cache_time = None  # monotonic timestamp of last real check, None = invalid
_log = logging.getLogger("obs-launcher")


def _setup_logging(log_file: str | None) -> None:
    """Configure rotating file + console logging."""
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    _log.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    _log.addHandler(ch)
    if log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=5_000_000, backupCount=2)
        fh.setFormatter(fmt)
        _log.addHandler(fh)


def _is_obs_running() -> bool:
    """Check if obs64.exe is running on Windows."""
    try:
        result = subprocess.run(
            ["/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe", "-Command", "Get-Process obs64 -ErrorAction SilentlyContinue"],
            capture_output=True, text=True, timeout=10,
        )
        return "obs64" in result.stdout.lower()
    except Exception as e:
        _log.warning("Failed to check OBS process: %s", e)
        return False


def _obs_running_cached() -> bool:
    """_is_obs_running() cached for STATUS_CACHE_TTL seconds (thread-safe)."""
    global _cache_value, _cache_time
    with _cache_lock:
        now = time.monotonic()
        if _cache_time is not None and now - _cache_time < STATUS_CACHE_TTL:
            return _cache_value
        _cache_value = _is_obs_running()
        _cache_time = time.monotonic()
        return _cache_value


def _invalidate_cache() -> None:
    global _cache_time
    with _cache_lock:
        _cache_time = None


def _host_allowed(host_header: str | None) -> bool:
    """True if the Host header's hostname (port stripped) is on the allowlist."""
    if not host_header:
        return False
    host = host_header.strip().lower()
    if host.startswith("["):
        end = host.find("]")
        if end == -1:
            return False
        name = host[1:end]
    elif host.count(":") == 1:
        name = host.split(":", 1)[0]
    else:
        name = host
    return name in ALLOWED_HOSTS


def _ps_escape(s: str) -> str:
    """Escape a string for safe use inside PowerShell double quotes."""
    return s.replace("`", "``").replace('"', '`"').replace("$", "`$")


def _launch_obs(obs_path: str) -> bool:
    """Start OBS on Windows via powershell."""
    if _is_obs_running():
        _log.info("OBS already running")
        return True
    try:
        obs_dir = ntpath.dirname(obs_path)
        safe_path = _ps_escape(obs_path)
        safe_dir = _ps_escape(obs_dir)
        subprocess.Popen(
            ["/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe", "-Command",
             f'Start-Process "{safe_path}" -WorkingDirectory "{safe_dir}"'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _log.info("OBS launch command sent")
        return True
    except Exception as e:
        _log.error("Failed to launch OBS: %s", e)
        return False


def _kill_obs() -> bool:
    """Stop OBS on Windows via powershell."""
    try:
        subprocess.run(
            ["/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe", "-Command", "Stop-Process -Name obs64 -Force -ErrorAction SilentlyContinue"],
            capture_output=True, timeout=10,
        )
        _log.info("OBS kill command sent")
        return True
    except Exception as e:
        _log.error("Failed to kill OBS: %s", e)
        return False


class Handler(BaseHTTPRequestHandler):
    obs_path = DEFAULT_OBS_PATH
    timeout = 15  # per-connection socket timeout; stops stalled clients holding a thread

    def _respond(self, data: dict, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _precheck(self) -> bool:
        """Host and Origin checks for every request. Responds and returns False on reject."""
        if not _host_allowed(self.headers.get("Host")):
            self._respond({"error": "forbidden host"}, 403)
            return False
        if self.headers.get("Origin") is not None:
            self._respond({"error": "forbidden origin"}, 403)
            return False
        return True

    def _authorized(self) -> bool:
        """Bearer-token check. Responds and returns False on failure."""
        if not _TOKEN:
            self._respond({"error": "launcher auth not configured"}, 503)
            return False
        header = self.headers.get("Authorization") or ""
        prefix = "Bearer "
        supplied = header[len(prefix):] if header.startswith(prefix) else ""
        if not hmac.compare_digest(supplied.encode(), _TOKEN.encode()):
            self._respond({"error": "unauthorized"}, 401)
            return False
        return True

    def do_GET(self) -> None:
        if not self._precheck():
            return
        if self.path == "/status":
            if not self._authorized():
                return
            self._respond({"running": _obs_running_cached()})
        elif self.path == "/health":
            self._respond({
                "status": "ok",
                "uptime_seconds": int(time.time() - _START_TIME),
                "pid": os.getpid(),
            })
        else:
            self._respond({"error": "not found"}, 404)

    def do_POST(self) -> None:
        if not self._precheck():
            return
        if self.path in ("/launch", "/kill"):
            if not self._authorized():
                return
            _invalidate_cache()
            try:
                if self.path == "/launch":
                    ok = _launch_obs(self.obs_path)
                    self._respond({"launched": ok, "running": _is_obs_running()})
                else:
                    _kill_obs()
                    self._respond({"running": _is_obs_running()})
            finally:
                _invalidate_cache()
        else:
            self._respond({"error": "not found"}, 404)

    def log_message(self, fmt, *args) -> None:
        line = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", str(args[0]) if args else "")
        _log.info("%s", line[:200])


def main() -> None:
    parser = argparse.ArgumentParser(description="OBS launcher HTTP server for WSL2")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Listen port (default: {DEFAULT_PORT})")
    parser.add_argument("--obs-path", default=DEFAULT_OBS_PATH, help="Windows path to obs64.exe")
    parser.add_argument("--log-file", default=os.path.expanduser("~/.openclaw/obs-launcher.log"),
                        help="Log file path (default: ~/.openclaw/obs-launcher.log)")
    args = parser.parse_args()

    _setup_logging(args.log_file)

    global _TOKEN
    _TOKEN = os.environ.get("OBS_LAUNCHER_TOKEN", "")
    if not _TOKEN:
        _log.warning("OBS_LAUNCHER_TOKEN not set: /status, /launch, /kill will return 503")

    Handler.obs_path = args.obs_path
    ThreadingHTTPServer.daemon_threads = True
    # 0.0.0.0 on purpose: Docker Desktop (WSL2 NAT) containers reach us via host.docker.internal.
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    _log.info("OBS launcher listening on :%d (PID %d)", args.port, os.getpid())
    _log.info("OBS path: %s", args.obs_path)
    _log.info("Log file: %s", args.log_file)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _log.info("Stopped")


if __name__ == "__main__":
    main()
