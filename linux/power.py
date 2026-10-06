"""Notice when the session locks or the machine sleeps, so the dock can go dark.

- Lock: Hyprland lists "LOCK" in a monitor's `solitaryBlockedBy` while an ext-session-lock
  is active (any locker: omarchy-shell, hyprlock, …). Polled with `hyprctl -j monitors`.
- Sleep: logind's PrepareForSleep(true/false) on the system bus, streamed by `dbus-monitor`.

Both degrade quietly: if the tool is missing or fails, that monitor logs once and stops.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from herdr_core.ports import Sleep
from linux.hyprland import Exec, run_exec

log = logging.getLogger(__name__)

SLEEP_SIGNAL = (
    "type='signal',sender='org.freedesktop.login1',"
    "interface='org.freedesktop.login1.Manager',member='PrepareForSleep'"
)


def session_locked(monitors: Any) -> bool:
    return isinstance(monitors, list) and any(
        isinstance(m, dict) and "LOCK" in (m.get("solitaryBlockedBy") or []) for m in monitors
    )


class LockMonitor:
    def __init__(
        self,
        on_change: Callable[[bool], None],
        *,
        interval: float = 1.0,
        run: Exec = run_exec,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._on_change = on_change
        self._interval = interval
        self._run = run
        self._sleep = sleep
        self._locked = False

    async def check(self) -> bool | None:
        """Current lock state, or None if Hyprland can't be asked."""
        code, out = await self._run(["hyprctl", "-j", "monitors"])
        if code != 0:
            return None
        try:
            return session_locked(json.loads(out))
        except json.JSONDecodeError:
            return None

    async def run(self) -> None:
        failures = 0
        while True:
            locked = await self.check()
            if locked is None:
                failures += 1
                if failures == 3:
                    log.warning("can't read the lock state from hyprctl; lock blanking is off")
                    return
            else:
                failures = 0
                if locked != self._locked:
                    self._locked = locked
                    log.info("session %s", "locked" if locked else "unlocked")
                    self._on_change(locked)
            await self._sleep(self._interval)


class SleepMonitor:
    RESTART_SECONDS = 30.0

    def __init__(
        self,
        on_change: Callable[[bool], None],
        *,
        spawn: Callable[..., Any] = asyncio.create_subprocess_exec,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._on_change = on_change
        self._spawn = spawn
        self._sleep = sleep

    async def run(self) -> None:
        while True:
            try:
                process = await self._spawn(
                    "dbus-monitor",
                    "--system",
                    SLEEP_SIGNAL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            except OSError as exc:
                log.warning("dbus-monitor unavailable (%s); sleep blanking is off", exc)
                return
            try:
                await self._follow(process.stdout)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
            log.info("dbus-monitor exited; restarting in %.0fs", self.RESTART_SECONDS)
            await self._sleep(self.RESTART_SECONDS)

    async def _follow(self, stdout: asyncio.StreamReader) -> None:
        while line := await stdout.readline():
            text = line.decode(errors="replace").strip()
            if text == "boolean true":
                log.info("system going to sleep")
                self._on_change(True)
            elif text == "boolean false":
                log.info("system resumed")
                self._on_change(False)
