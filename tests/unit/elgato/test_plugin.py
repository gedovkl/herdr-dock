from __future__ import annotations

import asyncio
import json

from elgato.grid import ACTION_UUID, ElgatoGrid
from herdr_core.faces import KeyLayout
from streamdock_plugin.lifecycle import VisibilityLifecycle
from streamdock_plugin.plugin import HerdrPlugin
from streamdock_plugin.surface import StreamDockSurface


class Transport:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


class Presenter:
    def invalidate(self) -> None: ...


class Session:
    def __init__(self) -> None:
        self.pressed: list[int] = []

    async def press(self, key_index: int) -> None:
        self.pressed.append(key_index)


def key_event(event: str, context: str, column: int, row: int, device: str = "phone") -> str:
    return json.dumps(
        {
            "event": event,
            "action": ACTION_UUID,
            "context": context,
            "device": device,
            "payload": {"controller": "Keypad", "coordinates": {"column": column, "row": row}},
        }
    )


async def test_keys_count_from_the_top_left_and_every_key_shows_an_agent() -> None:
    transport, session = Transport(), Session()
    surface = StreamDockSurface(transport)

    async def nothing() -> None: ...

    plugin = HerdrPlugin(
        surface,
        VisibilityLifecycle(nothing, nothing, grace=0),
        Presenter(),
        session,
        KeyLayout(exit_key=False),
        ElgatoGrid(5, 3),
        ACTION_UUID,
    )
    plugin.handle(key_event("willAppear", "top-left", 0, 0))
    plugin.handle(key_event("willAppear", "second-row", 1, 1))
    assert surface.key_of("top-left") == 0  # unlike VSD, key 0 is a normal agent key
    assert surface.key_of("second-row") == 6

    plugin.handle(key_event("keyUp", "second-row", 1, 1))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert session.pressed == [6]
    await plugin.close()
