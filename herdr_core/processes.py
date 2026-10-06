"""OS-independent helpers for finding the terminal that hosts the herdr client."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

Exec = Callable[[Sequence[str]], Awaitable[tuple[int, str]]]


@dataclass(frozen=True, slots=True)
class Process:
    pid: int
    ppid: int
    argv: tuple[str, ...]


async def run_exec(argv: Sequence[str], timeout: float = 5.0) -> tuple[int, str]:
    """Run a command without a shell; returns (exit code, stdout). 127 = couldn't start it."""
    try:
        process = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
    except OSError:
        return 127, ""
    try:
        out, _ = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        return -1, ""
    return process.returncode or 0, out.decode(errors="replace")


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


def ancestors(pid: int, processes: dict[int, Process]) -> Iterator[Process]:
    """`pid` itself, then its parent, grandparent... until the table or the chain ends."""
    seen: set[int] = set()
    while pid > 1 and pid not in seen and pid in processes:
        seen.add(pid)
        process = processes[pid]
        yield process
        pid = process.ppid
