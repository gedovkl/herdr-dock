"""Raise the window the herdr client is running in (Hyprland)."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from herdr_core.models import Agent

log = logging.getLogger(__name__)

Exec = Callable[[Sequence[str]], Awaitable[tuple[int, str]]]


@dataclass(frozen=True, slots=True)
class Process:
    pid: int
    ppid: int
    argv: tuple[str, ...]


async def run_exec(argv: Sequence[str], timeout: float = 5.0) -> tuple[int, str]:
    """Run a command without a shell; returns (exit code, stdout)."""
    process = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    try:
        out, _ = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        return -1, ""
    return process.returncode or 0, out.decode(errors="replace")


def read_processes(proc: Path = Path("/proc")) -> dict[int, Process]:
    processes: dict[int, Process] = {}
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
            cmdline = (entry / "cmdline").read_bytes()
        except OSError:
            continue  # the process went away
        # comm (field 2) may contain spaces/parens; ppid is the 2nd field after the last ")".
        ppid = int(stat[stat.rindex(")") + 2 :].split()[1])
        argv = tuple(part.decode(errors="replace") for part in cmdline.split(b"\0") if part)
        processes[int(entry.name)] = Process(int(entry.name), ppid, argv)
    return processes


def herdr_clients(processes: Iterable[Process]) -> list[Process]:
    """Attached herdr TUI clients (not `herdr server` or one-shot CLI calls)."""
    clients = []
    for process in processes:
        if not process.argv or Path(process.argv[0]).name != "herdr":
            continue
        rest = process.argv[1:]
        attached = (
            not rest or rest[0] in ("--session", "--remote") or rest[:2] == ("session", "attach")
        )
        if attached and "server" not in rest:
            clients.append(process)
    return clients


def window_for(
    clients: Iterable[Process], processes: dict[int, Process], windows: Sequence[dict[str, object]]
) -> str | None:
    """Address of the most recently focused window that is an ancestor of a herdr client."""
    by_pid: dict[int, dict[str, object]] = {}
    for window in windows:
        pid = window.get("pid")
        if isinstance(pid, int):
            by_pid.setdefault(pid, window)
    candidates = []
    for client in clients:
        pid, seen = client.pid, set()
        while pid > 1 and pid not in seen:
            seen.add(pid)
            if pid in by_pid:
                candidates.append(by_pid[pid])
                break
            parent = processes.get(pid)
            if parent is None:
                break
            pid = parent.ppid
    if not candidates:
        return None
    best = min(candidates, key=lambda w: _history(w))
    address = best.get("address")
    return address if isinstance(address, str) else None


def _history(window: dict[str, object]) -> int:
    value = window.get("focusHistoryID")
    return value if isinstance(value, int) else 1_000_000


class HerdrWindowRaiser:
    """Implements Raiser: focuses the terminal window hosting the herdr client."""

    def __init__(
        self,
        run: Exec = run_exec,
        processes: Callable[[], dict[int, Process]] = read_processes,
    ) -> None:
        self._run = run
        self._processes = processes

    async def raise_window(self, agent: Agent) -> None:
        code, out = await self._run(["hyprctl", "clients", "-j"])
        if code != 0:
            log.warning("hyprctl clients failed (%s); is Hyprland running?", code)
            return
        try:
            windows = json.loads(out)
        except json.JSONDecodeError:
            log.warning("hyprctl clients returned invalid JSON")
            return
        processes = self._processes()
        address = window_for(herdr_clients(processes.values()), processes, windows)
        if address is None:
            log.info("no window found for a herdr client")
            return
        selector = f"address:{address}"
        # Hyprland >= 0.55 uses Lua dispatchers; older versions take `focuswindow <selector>`.
        for argv in (
            ["hyprctl", "dispatch", f'hl.dsp.focus({{ window = "{selector}" }})'],
            ["hyprctl", "dispatch", "focuswindow", selector],
        ):
            code, out = await self._run(argv)
            if code == 0 and out.strip() == "ok":
                return
        log.warning("could not focus window %s", address)
