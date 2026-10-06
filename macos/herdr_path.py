"""Find the `herdr` binary from a plugin process.

The StreamDock app starts plugins with `PATH=/usr/bin:/bin:/usr/sbin:/sbin;…`, which has none of
the places herdr gets installed.
"""

from __future__ import annotations

import os
from pathlib import Path

from herdr_core.socket_path import StatusReader, read_herdr_status


def _install_dirs(home: Path) -> tuple[Path, ...]:
    return (
        home / ".local" / "bin",
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
        home / ".cargo" / "bin",
    )


def find_herdr(path_env: str, home: Path) -> Path | None:
    """`herdr` on `path_env`, else in the usual install directories."""
    directories = [Path(entry) for entry in path_env.split(os.pathsep) if entry]
    for directory in (*directories, *_install_dirs(home)):
        candidate = directory / "herdr"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def herdr_status_reader(path_env: str, home: Path) -> StatusReader:
    """A `herdr status server` reader that runs the binary found by `find_herdr`."""
    binary = find_herdr(path_env, home)
    if binary is None:
        return lambda: None
    return lambda: read_herdr_status(str(binary))
