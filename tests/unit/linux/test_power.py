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


async def run_until_done(monitor: Any, sleeps: list[float]) -> None:
    await asyncio.wait_for(monitor.run(), 2.0)


async def test_lock_monitor_reports_changes_only_and_gives_up_without_hyprctl(
    caplog: pytest.LogCaptureFixture,
) -> None:
    changes: list[bool] = []
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    hyprctl = Hyprctl(UNLOCKED, LOCKED, LOCKED, "garbage", UNLOCKED, None, None, None)
    monitor = LockMonitor(changes.append, interval=0.5, run=hyprctl, sleep=sleep)
    await run_until_done(monitor, sleeps)
    assert changes == [True, False]  # unlocked at start is not a change
    assert set(sleeps) == {0.5}
    assert "lock blanking is off" in caplog.text


class FakeProcess:
    def __init__(self, lines: list[bytes]) -> None:
        self.stdout = asyncio.StreamReader()
        for line in lines:
            self.stdout.feed_data(line)
        self.stdout.feed_eof()
        self.returncode: int | None = None
        self.killed = False

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode or 0


async def test_sleep_monitor_follows_prepare_for_sleep_and_restarts() -> None:
    changes: list[bool] = []
    spawned: list[tuple[Any, ...]] = []
    runs = [
        FakeProcess([b"signal time=1 ...\n", b"   boolean true\n", b"   boolean false\n"]),
        FakeProcess([b"   boolean true\n"]),
    ]

    async def spawn(*argv: Any, **kwargs: Any) -> FakeProcess:
        spawned.append(argv)
        if not runs:
            raise FileNotFoundError("dbus-monitor")
        return runs.pop(0)

    async def sleep(seconds: float) -> None:
        assert seconds == SleepMonitor.RESTART_SECONDS

    await asyncio.wait_for(SleepMonitor(changes.append, spawn=spawn, sleep=sleep).run(), 2.0)
    assert changes == [True, False, True]
    assert spawned[0] == ("dbus-monitor", "--system", SLEEP_SIGNAL)
    assert len(spawned) == 3  # restarted after each exit, gave up when it couldn't start


async def test_sleep_monitor_without_dbus_monitor(caplog: pytest.LogCaptureFixture) -> None:
    async def spawn(*argv: Any, **kwargs: Any) -> FakeProcess:
        raise FileNotFoundError("dbus-monitor")

    await SleepMonitor(lambda asleep: None, spawn=spawn).run()
    assert "sleep blanking is off" in caplog.text


async def test_lock_check_is_none_when_hyprctl_fails() -> None:
    result = await LockMonitor(lambda locked: None, run=Hyprctl(None)).check()
    assert result is None
