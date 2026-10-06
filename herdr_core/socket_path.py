"""Locate the herdr server socket."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

StatusReader = Callable[[], str | None]


def read_herdr_status(herdr: str = "herdr") -> str | None:
    """Output of `herdr status server`, or None if herdr isn't installed or hangs.

    `herdr` is the binary to run: a front end with a minimal PATH passes an absolute path.
    """
    try:
        done = subprocess.run(
            [herdr, "status", "server"], capture_output=True, text=True, timeout=3, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout


def resolve_socket_path(
    explicit: str,
    env: Mapping[str, str],
    home: Path,
    read_status: StatusReader = read_herdr_status,
) -> Path:
    """Config value, then $HERDR_SOCKET, then `herdr status server`, then the default path."""
    if explicit:
        return Path(explicit).expanduser()
    if env.get("HERDR_SOCKET"):
        return Path(env["HERDR_SOCKET"]).expanduser()
    output = read_status()
    for line in (output or "").splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "socket" and value.strip():
            return Path(value.strip())
    return home / ".config" / "herdr" / "herdr.sock"
