"""Shared path utilities for cron helper scripts."""

import os

RENDERS_DIR = "/home/node/clawd-twitch/renders"


def to_windows_path(docker_path: str, renders_dir: str = RENDERS_DIR) -> str:
    """Convert a Docker render path to a Windows-accessible path.

    If OBS_RENDERS_WIN_PREFIX is set, replaces the Docker renders dir prefix
    with the Windows UNC/local prefix. Otherwise returns the path as-is.
    """
    prefix = os.environ.get("OBS_RENDERS_WIN_PREFIX", "")
    if prefix:
        rel_path = os.path.relpath(docker_path, renders_dir)
        return f"{prefix.rstrip(chr(92))}\\{rel_path.replace('/', chr(92))}"
    return docker_path
