"""Start apps and commands from home-page keys, detached from the daemon."""

from __future__ import annotations

import logging
import shlex
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

Spawn = Callable[..., Any]


class ShellLauncher:
    def __init__(self, app_launcher: str = "uwsm-app -- {app}", spawn: Spawn = subprocess.Popen):
        self._app_launcher = app_launcher
        self._spawn = spawn

    def app_command(self, app: str) -> str:
        return self._app_launcher.replace("{app}", shlex.quote(app))

    def run(self, command: str) -> None:
        try:
            self._spawn(
                command,
                shell=True,
                start_new_session=True,  # survives daemon restarts, gets its own process group
                cwd=Path.home(),  # not the daemon's working directory (the SDK's temp folder)
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            log.warning("could not start %r: %s", command, exc)

    def app(self, app: str) -> None:
        self.run(self.app_command(app))
