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
import ntpath
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler

DEFAULT_PORT = 8100
DEFAULT_OBS_PATH = r"C:\Program Files\obs-studio\bin\64bit\obs64.exe"


def _is_obs_running() -> bool:
    """Check if obs64.exe is running on Windows."""
    try:
        result = subprocess.run(
            ["/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe", "-Command", "Get-Process obs64 -ErrorAction SilentlyContinue"],
            capture_output=True, text=True, timeout=10,
        )
        return "obs64" in result.stdout.lower()
    except Exception:
        return False


def _launch_obs(obs_path: str) -> bool:
    """Start OBS on Windows via powershell."""
    if _is_obs_running():
        return True
    try:
        obs_dir = ntpath.dirname(obs_path)
        subprocess.Popen(
            ["/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe", "-Command",
             f'Start-Process "{obs_path}" -WorkingDirectory "{obs_dir}"'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def _kill_obs() -> bool:
    """Stop OBS on Windows via powershell."""
    try:
        subprocess.run(
            ["/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe", "-Command", "Stop-Process -Name obs64 -Force -ErrorAction SilentlyContinue"],
            capture_output=True, timeout=10,
        )
        return True
    except Exception:
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
        print(f"[obs-launcher] {args[0]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="OBS launcher HTTP server for WSL2")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Listen port (default: {DEFAULT_PORT})")
    parser.add_argument("--obs-path", default=DEFAULT_OBS_PATH, help="Windows path to obs64.exe")
    args = parser.parse_args()

    Handler.obs_path = args.obs_path
    server = HTTPServer(("0.0.0.0", args.port), Handler)
    print(f"OBS launcher listening on :{args.port}")
    print(f"OBS path: {args.obs_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")


if __name__ == "__main__":
    main()
