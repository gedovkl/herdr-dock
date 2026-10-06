from __future__ import annotations

import asyncio
import json
import logging

import pytest

from herdr_core.faces import KeyLayout
from macos.lifecycle import VisibilityLifecycle
from macos.plugin import ACTION_UUID, HerdrPlugin
from macos.surface import StreamDockSurface


class FakeTransport:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


class FakePresenter:
    def __init__(self) -> None:
        self.invalidated = 0

    def invalidate(self) -> None:
        self.invalidated += 1


class FakeSession:
    def __init__(self) -> None:
        self.pressed: list[int] = []
        self.fail = False

    async def press(self, key_index: int) -> None:
        if self.fail:
            raise RuntimeError("boom")
        self.pressed.append(key_index)


class Rig:
    def __init__(self) -> None:
        self.transport = FakeTransport()
        self.surface = StreamDockSurface(self.transport)
        self.presenter = FakePresenter()
        self.session = FakeSession()
        self.calls: list[str] = []

        async def start() -> None:
            self.calls.append("start")

        async def stop() -> None:
            self.calls.append("stop")

        async def no_wait(_: float) -> None:
            return None

        self.lifecycle = VisibilityLifecycle(start, stop, grace=0, sleep=no_wait)
        self.plugin = HerdrPlugin(
            self.surface, self.lifecycle, self.presenter, self.session, KeyLayout(exit_key=True)
        )

    def send(self, event: str, context: str, column: int, row: int, **extra: object) -> None:
        self.plugin.handle(
            json.dumps(
                {
                    "event": event,
                    "action": extra.pop("action", ACTION_UUID),
                    "context": context,
                    "device": extra.pop("device", "m18"),
                    "payload": {"coordinates": {"column": column, "row": row}},
                }
            )
        )

    def connect(self, device: str, columns: int, rows: int) -> None:
        self.plugin.handle(
            json.dumps(
                {
                    "event": "deviceDidConnect",
                    "device": device,
                    "deviceInfo": {"name": "x", "size": {"columns": columns, "rows": rows}},
                }
            )
        )

    async def settle(self) -> None:
        for _ in range(10):
            await asyncio.sleep(0)

    async def close(self) -> None:
        await self.plugin.close()


@pytest.fixture
async def rig() -> Rig:
    return Rig()


async def test_appearing_attaches_the_key_redraws_and_starts_herdr(rig: Rig) -> None:
    rig.send("willAppear", "c1", column=1, row=0)  # key index 1 = the first agent slot
    await rig.settle()
    assert rig.surface.key_of("c1") == 1
    assert rig.presenter.invalidated == 1
    assert rig.calls == ["start"]
    await rig.close()


async def test_key_index_is_row_major(rig: Rig) -> None:
    rig.send("willAppear", "c1", column=3, row=2)
    assert rig.surface.key_of("c1") == 13
    await rig.close()


async def test_disappearing_detaches_and_eventually_stops(rig: Rig) -> None:
    rig.send("willAppear", "c1", column=1, row=0)
    await rig.settle()
    rig.send("willDisappear", "c1", column=1, row=0)
    await rig.settle()
    assert rig.surface.count == 0
    assert rig.calls == ["start", "stop"]
    await rig.close()


async def test_a_dragged_key_moves(rig: Rig) -> None:
    rig.send("willAppear", "c1", column=1, row=0)
    rig.send("willAppear", "c1", column=2, row=0)
    assert rig.surface.key_of("c1") == 2
    assert rig.surface.count == 1
    await rig.close()


async def test_the_apps_back_key_is_never_ours(rig: Rig) -> None:
    rig.send("willAppear", "c1", column=0, row=0)
    await rig.settle()
    assert rig.surface.count == 0
    assert rig.calls == []
    rig.send("keyUp", "c1", column=0, row=0)
    await rig.settle()
    assert rig.session.pressed == []
    await rig.close()


async def test_other_actions_are_ignored(rig: Rig) -> None:
    rig.send("willAppear", "c1", column=1, row=0, action="com.someone.else")
    await rig.settle()
    assert rig.surface.count == 0
    assert rig.calls == []
    await rig.close()


async def test_key_up_presses_the_session_slot(rig: Rig) -> None:
    rig.send("willAppear", "c1", column=1, row=0)
    rig.send("keyUp", "c1", column=1, row=0)  # key 1 → session index 0
    rig.send("keyUp", "c1", column=4, row=2)  # key 14 → session index 13 (the pager slot)
    await rig.settle()
    assert rig.session.pressed == [0, 13]
    await rig.close()


async def test_a_failing_press_is_logged_not_raised(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    rig.session.fail = True
    with caplog.at_level(logging.ERROR):
        rig.send("keyUp", "c1", column=2, row=0)
        await rig.settle()
    assert "press" in caplog.text
    await rig.close()


async def test_only_the_five_by_three_dock_is_used(rig: Rig) -> None:
    rig.connect("n3", columns=4, rows=3)
    rig.send("willAppear", "c1", column=1, row=0, device="n3")
    await rig.settle()
    assert rig.surface.count == 0
    rig.connect("m18", columns=5, rows=3)
    rig.send("willAppear", "c2", column=1, row=0, device="m18")
    assert rig.surface.key_of("c2") == 1
    await rig.close()


async def test_the_first_dock_wins(rig: Rig) -> None:
    rig.send("willAppear", "c1", column=1, row=0, device="first")
    rig.send("willAppear", "c2", column=2, row=0, device="second")
    assert rig.surface.count == 1
    assert rig.surface.key_of("c1") == 1
    await rig.close()


async def test_the_dock_can_come_back_after_unplugging(rig: Rig) -> None:
    rig.send("willAppear", "c1", column=1, row=0, device="first")
    rig.plugin.handle(json.dumps({"event": "deviceDidDisconnect", "device": "first"}))
    rig.send("willAppear", "c2", column=2, row=0, device="second")
    assert rig.surface.key_of("c2") == 2
    await rig.close()


async def test_garbage_is_ignored(rig: Rig) -> None:
    rig.plugin.handle("not json")
    rig.plugin.handle(json.dumps({"event": "somethingNew"}))
    await rig.close()


async def test_close_stops_herdr(rig: Rig) -> None:
    rig.send("willAppear", "c1", column=1, row=0)
    await rig.settle()
    await rig.close()
    assert rig.calls == ["start", "stop"]


async def test_appearing_pressing_and_disappearing_are_logged(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        rig.send("willAppear", "c1", column=1, row=0)
        rig.send("keyUp", "c1", column=1, row=0)
        await rig.settle()  # herdr starts while the key is visible
        rig.send("willDisappear", "c1", column=1, row=0)
        await rig.settle()
    assert "key 2 appeared" in caplog.text
    assert "key 2 pressed" in caplog.text
    assert "key 2 disappeared" in caplog.text
    assert "starting" in caplog.text and "stopping" in caplog.text
    await rig.close()
