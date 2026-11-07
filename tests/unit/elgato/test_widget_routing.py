"""Widget actions go to WidgetKeys; agent keys are unaffected."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

from elgato.grid import ACTION_UUID, ElgatoGrid
from herdr_core.faces import KeyLayout
from streamdock_plugin.lifecycle import VisibilityLifecycle
from streamdock_plugin.plugin import HerdrPlugin
from streamdock_plugin.surface import StreamDockSurface
from tests.unit.elgato.test_plugin import Presenter, Session, Transport

CLOCK = "com.herdr.dock.clock"


class Widgets:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def handles(self, action: str) -> bool:
        return action == CLOCK

    def appeared(self, context: str, action: str, settings: Mapping[str, Any]) -> None:
        self.calls.append(("appeared", context, json.dumps(dict(settings))))

    def disappeared(self, context: str) -> None:
        self.calls.append(("disappeared", context))

    async def pressed(self, context: str, action: str, settings: Mapping[str, Any]) -> None:
        self.calls.append(("pressed", context))


def event(name: str, action: str, context: str, settings: object = None) -> str:
    payload: dict[str, object] = {"coordinates": {"column": 0, "row": 0}}
    if settings is not None:
        payload["settings"] = settings
    return json.dumps(
        {"event": name, "action": action, "context": context, "device": "phone", "payload": payload}
    )


async def test_widget_events_reach_widget_keys_and_agents_still_work() -> None:
    surface, session, widgets = StreamDockSurface(Transport()), Session(), Widgets()

    async def nothing() -> None: ...

    plugin = HerdrPlugin(
        surface,
        VisibilityLifecycle(nothing, nothing, grace=0),
        Presenter(),
        session,
        KeyLayout(exit_key=False),
        ElgatoGrid(3, 2),
        ACTION_UUID,
        key_count=6,
        widgets=widgets,
    )
    plugin.handle(event("willAppear", CLOCK, "c", {"hour12": True}))
    plugin.handle(event("keyUp", CLOCK, "c"))
    plugin.handle(event("willDisappear", CLOCK, "c"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert widgets.calls == [
        ("appeared", "c", '{"hour12": true}'),
        ("disappeared", "c"),
        ("pressed", "c"),
    ] or widgets.calls == [
        ("appeared", "c", '{"hour12": true}'),
        ("pressed", "c"),
        ("disappeared", "c"),
    ]
    assert surface.key_of("c") is None  # never an agent key

    plugin.handle(event("willAppear", ACTION_UUID, "a"))
    plugin.handle(event("keyUp", ACTION_UUID, "a"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert surface.key_of("a") == 0 and session.pressed == [0]
    await plugin.close()


async def test_a_failing_widget_press_is_logged_not_raised() -> None:
    class Failing(Widgets):
        async def pressed(self, context: str, action: str, settings: Mapping[str, Any]) -> None:
            raise RuntimeError("boom")

    async def nothing() -> None: ...

    plugin = HerdrPlugin(
        StreamDockSurface(Transport()),
        VisibilityLifecycle(nothing, nothing, grace=0),
        Presenter(),
        Session(),
        KeyLayout(exit_key=False),
        ElgatoGrid(3, 2),
        ACTION_UUID,
        widgets=Failing(),
    )
    plugin.handle(event("keyUp", CLOCK, "c"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await plugin.close()
