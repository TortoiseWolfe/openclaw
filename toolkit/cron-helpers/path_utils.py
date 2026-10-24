"""Shared path utilities for cron helper scripts."""

import os
import re

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


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def safe_join(base: str, *parts: str) -> str:
    """Join parts under base, refusing any result that escapes base.

    Resolves symlinks (realpath) before checking containment. Absolute
    parts are rejected outright.
    """
    for part in parts:
        if os.path.isabs(part):
            raise ValueError(f"absolute path component not allowed: {part!r}")
    base_real = os.path.realpath(base)
    target_real = os.path.realpath(os.path.join(base_real, *parts))
    if os.path.commonpath([base_real, target_real]) != base_real:
        raise ValueError(f"path escapes {base}: {os.path.join(*parts) if parts else ''}")
    return target_real


def require_slug(value: str, what: str = "value") -> str:
    """Return value if it is a lowercase slug, else raise ValueError."""
    if not isinstance(value, str) or not _SLUG_RE.fullmatch(value):
        raise ValueError(f"invalid {what}: {value!r} (expected lowercase letters, digits, hyphens)")
    return value


def require_date(value: str) -> str:
    """Return value if it looks like YYYY-MM-DD, else raise ValueError."""
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise ValueError(f"invalid date: {value!r} (expected YYYY-MM-DD)")
    return value
