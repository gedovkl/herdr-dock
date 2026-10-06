"""Notice when the session locks or the machine sleeps, so the dock can go dark.

- Lock: Hyprland lists "LOCK" in a monitor's `solitaryBlockedBy` while an ext-session-lock
  is active (any locker: omarchy-shell, hyprlock, …). Polled with `hyprctl -j monitors`.
- Sleep: logind's PrepareForSleep(true/false) on the system bus, streamed by `dbus-monitor`.

Both degrade quietly. The lock monitor keeps its last known state and retries with backoff while
hyprctl fails (guessing "unlocked" would light the dock on a locked machine). The sleep monitor
logs once and stops if dbus-monitor is missing.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
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
    MAX_RETRY_SECONDS = 30.0

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
        """Poll forever. While hyprctl fails, keep the last state and back off."""
        failures = 0
        while True:
            locked = await self.check()
            if locked is None:
                failures += 1
                if failures == 3:
                    log.warning("can't read the lock state from hyprctl; retrying with backoff")
            else:
                if failures >= 3:
                    log.info("lock state readable again")
                failures = 0
                if locked != self._locked:
                    self._locked = locked
                    log.info("session %s", "locked" if locked else "unlocked")
                    self._on_change(locked)
            await self._sleep(self._delay(failures))

    def _delay(self, failures: int) -> float:
        if failures == 0:
            return self._interval
        return float(min(self._interval * 2.0**failures, self.MAX_RETRY_SECONDS))


INHIBIT = (
    "systemd-inhibit",
    "--what=sleep",
    "--mode=delay",
    "--who=herdr-dock",
    "--why=Turn the StreamDock off before suspend",
    "sleep",
    "infinity",
)


class SleepMonitor:
    """Follows logind's PrepareForSleep and turns the dock off *before* the machine suspends.

    While awake it holds a logind delay inhibitor (systemd-inhibit), so suspend waits until
    `on_change(True)` has finished (at most `blank_timeout`), then releases it.
    """

    RESTART_SECONDS = 30.0

    def __init__(
        self,
        on_change: Callable[[bool], Awaitable[None]],
        *,
        spawn: Callable[..., Any] = asyncio.create_subprocess_exec,
        sleep: Sleep = asyncio.sleep,
        blank_timeout: float = 3.0,
    ) -> None:
        self._on_change = on_change
        self._spawn = spawn
        self._sleep = sleep
        self._blank_timeout = blank_timeout
        self._inhibitor: Any = None
        self._inhibit_warned = False

    async def run(self) -> None:
        while True:
            await self._take_inhibitor()
            try:
                process = await self._spawn(
                    "dbus-monitor",
                    "--system",
                    SLEEP_SIGNAL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            except OSError as exc:
                await self._release_inhibitor()
                log.warning("dbus-monitor unavailable (%s); sleep blanking is off", exc)
                return
            try:
                await self._follow(process.stdout)
            finally:
                await self._stop(process)
                await self._release_inhibitor()
            log.info("dbus-monitor exited; restarting in %.0fs", self.RESTART_SECONDS)
            await self._sleep(self.RESTART_SECONDS)

    async def _follow(self, stdout: asyncio.StreamReader) -> None:
        while line := await stdout.readline():
            text = line.decode(errors="replace").strip()
            if text == "boolean true":
                log.info("system going to sleep")
                await self._notify(True)
                await self._release_inhibitor()  # the dock is dark: let the suspend continue
            elif text == "boolean false":
                log.info("system resumed")
                await self._take_inhibitor()
                await self._notify(False)

    async def _notify(self, asleep: bool) -> None:
        try:
            await asyncio.wait_for(self._on_change(asleep), self._blank_timeout)
        except Exception:
            what = "off before sleep" if asleep else "back on after resume"
            log.warning("turning the dock %s failed", what, exc_info=True)

    async def _take_inhibitor(self) -> None:
        if self._inhibitor is not None:
            return
        try:
            self._inhibitor = await self._spawn(
                *INHIBIT, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
        except OSError as exc:
            if not self._inhibit_warned:
                log.warning(
                    "systemd-inhibit unavailable (%s); the dock may still be lit when suspend "
                    "starts",
                    exc,
                )
                self._inhibit_warned = True

    async def _release_inhibitor(self) -> None:
        inhibitor, self._inhibitor = self._inhibitor, None
        if inhibitor is not None:
            await self._stop(inhibitor)

    @staticmethod
    async def _stop(process: Any) -> None:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
