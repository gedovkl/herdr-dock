"""A key's `agent` setting (set in the Property Inspector) pins it to that agent number."""

from __future__ import annotations

import asyncio
import json

from elgato.grid import ACTION_UUID, ElgatoGrid
from herdr_core.faces import KeyLayout
from streamdock_plugin.lifecycle import VisibilityLifecycle
from streamdock_plugin.plugin import HerdrPlugin
from streamdock_plugin.protocol import Appeared, KeyReleased, parse_event
from streamdock_plugin.surface import StreamDockSurface
from tests.unit.elgato.test_plugin import Presenter, Session, Transport


def event(name: str, context: str, column: int, row: int, settings: object = None) -> str:
    payload: dict[str, object] = {"coordinates": {"column": column, "row": row}}
    if settings is not None:
        payload["settings"] = settings
    return json.dumps(
        {
            "event": name,
            "action": ACTION_UUID,
            "context": context,
            "device": "phone",
            "payload": payload,
        }
    )


def test_the_agent_setting_is_parsed() -> None:
    assert parse_event(event("willAppear", "c", 0, 0, {"agent": 2})) == Appeared(
        "c", "phone", ACTION_UUID, 0, 0, agent=2
    )
    assert parse_event(event("keyUp", "c", 0, 0, {"agent": "3"})) == KeyReleased(
        "c", "phone", ACTION_UUID, 0, 0, agent=3
    )
    for bad in ({"agent": ""}, {"agent": "x"}, {"agent": 0}, {"agent": True}, {}, "junk"):
        parsed = parse_event(event("willAppear", "c", 0, 0, bad))
        assert isinstance(parsed, Appeared) and parsed.agent is None
    assert parse_event(event("willAppear", "c", 0, 0)) == Appeared("c", "phone", ACTION_UUID, 0, 0)


def test_changed_settings_arrive_like_a_new_appearance() -> None:
    parsed = parse_event(event("didReceiveSettings", "c", 1, 0, {"agent": 4}))
    assert parsed == Appeared("c", "phone", ACTION_UUID, 1, 0, agent=4)


def make(layout: KeyLayout) -> tuple[HerdrPlugin, StreamDockSurface, Session]:
    surface, session = StreamDockSurface(Transport()), Session()

    async def nothing() -> None: ...

    plugin = HerdrPlugin(
        surface,
        VisibilityLifecycle(nothing, nothing, grace=0),
        Presenter(),
        session,
        layout,
        ElgatoGrid(3, 2),
        ACTION_UUID,
        key_count=6,
    )
    return plugin, surface, session


async def test_a_numbered_key_shows_and_presses_that_agent() -> None:
    plugin, surface, session = make(KeyLayout(exit_key=False))
    plugin.handle(event("willAppear", "right", 2, 0, {"agent": 1}))
    plugin.handle(event("willAppear", "plain", 1, 1))
    assert surface.key_of("right") == 0  # agent 1, although it sits on key 3
    assert surface.key_of("plain") == 4  # no setting: its position, as before

    plugin.handle(event("keyUp", "right", 2, 0, {"agent": 1}))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert session.pressed == [0]
    await plugin.close()


async def test_changing_the_number_moves_the_key() -> None:
    plugin, surface, _ = make(KeyLayout(exit_key=False))
    plugin.handle(event("willAppear", "k", 2, 0, {"agent": 1}))
    plugin.handle(event("didReceiveSettings", "k", 2, 0, {"agent": 2}))
    assert surface.key_of("k") == 1
    plugin.handle(event("didReceiveSettings", "k", 2, 0, {}))  # cleared: back to its position
    assert surface.key_of("k") == 2
    await plugin.close()


async def test_with_an_exit_key_agent_1_is_the_first_agent_key() -> None:
    plugin, surface, session = make(KeyLayout(exit_key=True))
    plugin.handle(event("willAppear", "k", 2, 1, {"agent": 1}))
    assert surface.key_of("k") == 1
    plugin.handle(event("keyUp", "k", 2, 1, {"agent": 1}))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert session.pressed == [0]
    await plugin.close()


async def test_a_number_beyond_the_deck_falls_back_to_the_position() -> None:
    plugin, surface, _ = make(KeyLayout(exit_key=False))
    plugin.handle(event("willAppear", "k", 1, 0, {"agent": 9}))
    assert surface.key_of("k") == 1
    await plugin.close()
