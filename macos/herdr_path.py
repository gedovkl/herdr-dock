"""Find the `herdr` binary from a plugin process.

The StreamDock app starts plugins with `PATH=/usr/bin:/bin:/usr/sbin:/sbin;…`, which has none of
the places herdr gets installed.
"""

from __future__ import annotations

import os
from pathlib import Path

from herdr_core.socket_path import StatusReader, status_reader

SYSTEM_DIRS: tuple[Path, ...] = (Path("/opt/homebrew/bin"), Path("/usr/local/bin"))


def _install_dirs(home: Path) -> tuple[Path, ...]:
    return (home / ".local" / "bin", *SYSTEM_DIRS, home / ".cargo" / "bin")


def find_herdr(path_env: str, home: Path, configured: str = "") -> Path | None:
    """The configured binary, else `herdr` on `path_env`, else in the usual install directories."""
    if configured:
        return Path(configured).expanduser()
    directories = [Path(entry) for entry in path_env.split(os.pathsep) if entry]
    for directory in (*directories, *_install_dirs(home)):
        candidate = directory / "herdr"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def herdr_status_reader(path_env: str, home: Path, configured: str = "") -> StatusReader:
    """A `herdr status server` reader that runs the binary found by `find_herdr`."""
    binary = find_herdr(path_env, home, configured)
    if binary is None:
        return lambda: None
    return status_reader(str(binary))
