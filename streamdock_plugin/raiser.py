"""Bring the terminal that hosts the herdr client to the front on macOS."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from herdr_core.config import HERDR_WINDOW, RaiseConfig
from herdr_core.models import Agent
from herdr_core.processes import Exec, Process, ancestors, herdr_clients, run_exec
from herdr_core.raise_window import CommandRaiser, NullRaiser, raiser_from_config

log = logging.getLogger(__name__)

_APP_MARKER = ".app/Contents/MacOS/"


def parse_ps(output: str) -> dict[int, Process]:
    """Process table from `ps -axo pid=,ppid=,command=`. Lines that don't fit are skipped."""
    processes: dict[int, Process] = {}
    for line in output.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3 or not (parts[0].isdigit() and parts[1].isdigit()):
            continue
        processes[int(parts[0])] = Process(int(parts[0]), int(parts[1]), tuple(parts[2].split()))
    return processes


def app_bundle(command: str) -> Path | None:
    """`/Applications/X.app` for `/Applications/X.app/Contents/MacOS/x`, else None."""
    marker = command.find(_APP_MARKER)
    if marker < 0:
        return None
    return Path(command[: marker + len(".app")])


def terminal_app(clients: Iterable[Process], processes: dict[int, Process]) -> Path | None:
    """The application bundle nearest above the first herdr client that has one.

    A terminal with several windows is one process, and nothing here tells which window holds
    the client, so the whole app comes forward (its last used window stays on top).
    """
    for client in clients:
        for process in ancestors(client.pid, processes):
            bundle = app_bundle(" ".join(process.argv))
            if bundle is not None:
                return bundle
    return None


class TerminalRaiser:
    """Implements Raiser: `open`s the application that hosts the herdr client."""

    def __init__(self, run: Exec = run_exec) -> None:
        self._run = run

    async def raise_window(self, agent: Agent) -> None:
        code, output = await self._run(["ps", "-axo", "pid=,ppid=,command="])
        processes = parse_ps(output) if code == 0 else {}
        clients = sorted(herdr_clients(processes.values()), key=lambda process: process.pid)
        if not clients:
            log.info("no attached herdr client found; nothing to raise")
            return
        bundle = terminal_app(clients, processes)
        if bundle is None:
            log.info("no terminal app found above the herdr client")
            return
        code, _ = await self._run(["open", str(bundle)])
        if code != 0:
            log.warning("open %s exited with %s", bundle, code)


def macos_raiser(config: RaiseConfig) -> TerminalRaiser | CommandRaiser | NullRaiser:
    """`herdr-window` (or nothing configured) raises the herdr terminal; else the command."""
    if config.enabled and config.macos.strip() in ("", HERDR_WINDOW):
        return TerminalRaiser()
    return raiser_from_config(config, platform="darwin")
