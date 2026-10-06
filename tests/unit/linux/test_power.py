from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any

import pytest

from linux.power import SLEEP_SIGNAL, LockMonitor, SleepMonitor, session_locked

UNLOCKED = [{"name": "eDP-1", "solitaryBlockedBy": ["WINDOWED", "CANDIDATE"]}]
LOCKED = [{"name": "eDP-1", "solitaryBlockedBy": ["LOCK", "WINDOWED"]}, {"name": "DP-1"}]


def test_session_locked() -> None:
    assert session_locked(LOCKED)
    assert not session_locked(UNLOCKED)
    assert not session_locked([{"solitaryBlockedBy": None}, "junk"])
    assert not session_locked({"not": "a list"})


class Hyprctl:
    def __init__(self, *states: object) -> None:
        self.states = list(states)

    async def __call__(self, argv: Sequence[str]) -> tuple[int, str]:
        state = self.states.pop(0) if self.states else self.states_end
        if state is None:
            return 1, ""
        if state == "garbage":
            return 0, "not json"
        return 0, json.dumps(state)

    states_end: object = None


async def test_lock_monitor_reports_changes_only() -> None:
    changes: list[bool] = []
    sleeps: list[float] = []
    hyprctl = Hyprctl(UNLOCKED, LOCKED, LOCKED, UNLOCKED)

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if not hyprctl.states:
            raise asyncio.CancelledError  # stop the endless loop

    monitor = LockMonitor(changes.append, interval=0.5, run=hyprctl, sleep=sleep)
    with pytest.raises(asyncio.CancelledError):
        await monitor.run()
    assert changes == [True, False]  # unlocked at start is not a change
    assert set(sleeps) == {0.5}


async def test_lock_monitor_keeps_state_and_retries_while_hyprctl_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Never give up and never guess "unlocked": that would light the dock on a locked PC."""
    caplog.set_level("INFO")
    changes: list[bool] = []
    sleeps: list[float] = []
    hyprctl = Hyprctl(LOCKED, None, "garbage", None, None, None, None, LOCKED, UNLOCKED)

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if not hyprctl.states:
            raise asyncio.CancelledError

    monitor = LockMonitor(changes.append, interval=1.0, run=hyprctl, sleep=sleep)
    with pytest.raises(asyncio.CancelledError):
        await monitor.run()
    assert changes == [True, False]  # stayed locked through the failures, then unlocked
    assert max(sleeps) <= LockMonitor.MAX_RETRY_SECONDS
    assert sleeps[3] > 1.0  # backs off while failing
    assert caplog.text.count("can't read the lock state") == 1
    assert "lock state readable again" in caplog.text


class FakeProcess:
    def __init__(self, lines: list[bytes] | None = None, log: list[str] | None = None) -> None:
        self.stdout = asyncio.StreamReader()
        for line in lines or []:
            self.stdout.feed_data(line)
        if lines is not None:
            self.stdout.feed_eof()
        self.returncode: int | None = None
        self.log = log

    def kill(self) -> None:
        if self.log is not None and self.returncode is None:
            self.log.append("release inhibitor")
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode or 0


def spawner(monitors: list[FakeProcess], log: list[str], *, inhibit: bool = True) -> Any:
    calls: list[tuple[Any, ...]] = []

    async def spawn(*argv: Any, **kwargs: Any) -> FakeProcess:
        calls.append(argv)
        if argv[0] == "systemd-inhibit":
            if not inhibit:
                raise FileNotFoundError("systemd-inhibit")
            log.append("take inhibitor")
            return FakeProcess(log=log)
        if not monitors:
            raise FileNotFoundError("dbus-monitor")
        return monitors.pop(0)

    spawn.calls = calls  # type: ignore[attr-defined]
    return spawn


async def test_sleep_holds_a_delay_lock_until_the_dock_is_dark() -> None:
    log: list[str] = []

    async def on_change(asleep: bool) -> None:
        log.append(f"dock {'off' if asleep else 'on'}")

    monitor_output = [b"signal time=1 ...\n", b"   boolean true\n", b"   boolean false\n"]
    spawn = spawner([FakeProcess(monitor_output)], log)

    async def sleep(seconds: float) -> None:
        assert seconds == SleepMonitor.RESTART_SECONDS

    await asyncio.wait_for(SleepMonitor(on_change, spawn=spawn, sleep=sleep).run(), 2.0)
    assert log == [
        "take inhibitor",
        "dock off",  # blanked while logind waits for us...
        "release inhibitor",  # ...then suspend may proceed
        "take inhibitor",  # resumed: ready for the next suspend
        "dock on",
        "release inhibitor",  # dbus-monitor exited: cleaned up
        "take inhibitor",  # restart attempt...
        "release inhibitor",  # ...dbus-monitor missing: give up cleanly
    ]
    inhibit = next(c for c in spawn.calls if c[0] == "systemd-inhibit")
    assert "--mode=delay" in inhibit and "--what=sleep" in inhibit
    assert spawn.calls[1] == ("dbus-monitor", "--system", SLEEP_SIGNAL)


async def test_sleep_releases_the_lock_even_if_blanking_hangs_or_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    log: list[str] = []
    calls = 0

    async def on_change(asleep: bool) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            await asyncio.Event().wait()  # hangs
        raise RuntimeError("device gone")

    spawn = spawner([FakeProcess([b"boolean true\n", b"boolean false\n", b"boolean true\n"])], log)

    async def sleep(seconds: float) -> None:
        pass

    monitor = SleepMonitor(on_change, spawn=spawn, sleep=sleep, blank_timeout=0.05)
    await asyncio.wait_for(monitor.run(), 2.0)
    assert log.count("release inhibitor") == log.count("take inhibitor")
    assert "turning the dock off before sleep failed" in caplog.text


async def test_sleep_works_without_systemd_inhibit(caplog: pytest.LogCaptureFixture) -> None:
    log: list[str] = []
    changes: list[bool] = []

    async def on_change(asleep: bool) -> None:
        changes.append(asleep)

    spawn = spawner([FakeProcess([b"boolean true\n", b"boolean false\n"])], log, inhibit=False)

    async def sleep(seconds: float) -> None:
        pass

    await asyncio.wait_for(SleepMonitor(on_change, spawn=spawn, sleep=sleep).run(), 2.0)
    assert changes == [True, False]
    assert caplog.text.count("systemd-inhibit unavailable") == 1


async def test_sleep_monitor_without_dbus_monitor(caplog: pytest.LogCaptureFixture) -> None:
    async def on_change(asleep: bool) -> None:
        pass

    await SleepMonitor(on_change, spawn=spawner([], [])).run()
    assert "sleep blanking is off" in caplog.text


async def test_lock_check_is_none_when_hyprctl_fails() -> None:
    result = await LockMonitor(lambda locked: None, run=Hyprctl(None)).check()
    assert result is None
