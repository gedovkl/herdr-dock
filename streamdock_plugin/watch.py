"""Notice when a file changes, by polling (no OS-specific watcher, nothing to install)."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from pathlib import Path

from herdr_core.ports import Sleep

log = logging.getLogger(__name__)

Signature = tuple[int, int] | None
"""(modification time in ns, size), or None when the file doesn't exist."""


def file_signature(path: Path) -> Signature:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


class FileWatcher:
    """Calls `on_change` each time the file's signature differs from the last one seen."""

    def __init__(
        self,
        path: Path,
        on_change: Callable[[], None],
        *,
        interval: float = 1.0,
        sleep: Sleep = asyncio.sleep,
        signature: Callable[[Path], Signature] = file_signature,
    ) -> None:
        self._path = path
        self._on_change = on_change
        self._interval = interval
        self._sleep = sleep
        self._signature = signature

    async def run(self) -> None:
        """Poll until cancelled. The state at the start counts as 'seen', not as a change."""
        seen = self._signature(self._path)
        while True:
            await self._sleep(self._interval)
            current = self._signature(self._path)
            if current == seen:
                continue
            seen = current
            try:
                self._on_change()
            except Exception:
                log.exception("handling a change of %s failed", self._path)
