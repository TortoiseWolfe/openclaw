#!/usr/bin/env python3
"""Minimal HTTP server for launching OBS from WSL2.

Run this on the WSL2 host (outside Docker):
  python3 obs_launcher.py
  python3 obs_launcher.py --port 8100
  python3 obs_launcher.py --obs-path 'C:\\Program Files\\obs-studio\\bin\\64bit\\obs64.exe'

OpenClaw inside Docker calls this to start/stop OBS on the Windows host.
"""

import argparse
import json
import logging
import logging.handlers
import ntpath
import os
import subprocess
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

DEFAULT_PORT = 8100
DEFAULT_OBS_PATH = r"C:\Program Files\obs-studio\bin\64bit\obs64.exe"

_START_TIME = time.time()
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

    def _respond(self, data: dict, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self) -> None:
        if self.path == "/status":
            self._respond({"running": _is_obs_running()})
        elif self.path == "/health":
            self._respond({
                "status": "ok",
                "uptime_seconds": int(time.time() - _START_TIME),
                "pid": os.getpid(),
            })
        else:
            self._respond({"error": "not found"}, 404)

    def do_POST(self) -> None:
        if self.path == "/launch":
            ok = _launch_obs(self.obs_path)
            self._respond({"launched": ok, "running": _is_obs_running()})
        elif self.path == "/kill":
            _kill_obs()
            self._respond({"running": _is_obs_running()})
        else:
            self._respond({"error": "not found"}, 404)

    def log_message(self, fmt, *args) -> None:
        _log.info("%s", args[0])


def main() -> None:
    parser = argparse.ArgumentParser(description="OBS launcher HTTP server for WSL2")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Listen port (default: {DEFAULT_PORT})")
    parser.add_argument("--obs-path", default=DEFAULT_OBS_PATH, help="Windows path to obs64.exe")
    parser.add_argument("--log-file", default=os.path.expanduser("~/.openclaw/obs-launcher.log"),
                        help="Log file path (default: ~/.openclaw/obs-launcher.log)")
    args = parser.parse_args()

    _setup_logging(args.log_file)

    Handler.obs_path = args.obs_path
    server = HTTPServer(("0.0.0.0", args.port), Handler)
    _log.info("OBS launcher listening on :%d (PID %d)", args.port, os.getpid())
    _log.info("OBS path: %s", args.obs_path)
    _log.info("Log file: %s", args.log_file)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _log.info("Stopped")


if __name__ == "__main__":
    main()
