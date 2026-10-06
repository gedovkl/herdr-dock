from __future__ import annotations

import json

import pytest

from macos.surface import StreamDockSurface


class FakeTransport:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.fail = False

    def send(self, message: str) -> None:
        if self.fail:
            raise ConnectionError("closed")
        self.sent.append(json.loads(message))


async def test_show_sends_set_image_to_the_context_on_that_key() -> None:
    transport = FakeTransport()
    surface = StreamDockSurface(transport)
    surface.attach("c7", 6)
    await surface.show(6, b"png")
    assert [(m["event"], m["context"]) for m in transport.sent] == [("setImage", "c7")]


async def test_show_on_a_key_without_our_action_is_a_no_op() -> None:
    transport = FakeTransport()
    surface = StreamDockSurface(transport)
    await surface.show(0, b"png")  # the app's own back key
    assert transport.sent == []


async def test_detach_stops_drawing() -> None:
    transport = FakeTransport()
    surface = StreamDockSurface(transport)
    surface.attach("c1", 2)
    surface.detach("c1")
    await surface.show(2, b"png")
    assert transport.sent == []
    assert surface.count == 0


async def test_moving_a_context_frees_its_old_key() -> None:
    transport = FakeTransport()
    surface = StreamDockSurface(transport)
    surface.attach("c1", 2)
    surface.attach("c1", 3)
    await surface.show(2, b"png")
    await surface.show(3, b"png")
    assert [m["context"] for m in transport.sent] == ["c1"]
    assert surface.count == 1


async def test_a_new_context_replaces_a_stale_one_on_the_same_key() -> None:
    transport = FakeTransport()
    surface = StreamDockSurface(transport)
    surface.attach("old", 4)
    surface.attach("new", 4)
    await surface.show(4, b"png")
    assert [m["context"] for m in transport.sent] == ["new"]
    surface.detach("old")  # late disappear of the replaced context must not free "new"
    await surface.show(4, b"png")
    assert len(transport.sent) == 2


def test_key_of() -> None:
    surface = StreamDockSurface(FakeTransport())
    surface.attach("c1", 9)
    assert surface.key_of("c1") == 9
    assert surface.key_of("nope") is None


async def test_send_failures_propagate_so_the_presenter_retries() -> None:
    transport = FakeTransport()
    transport.fail = True
    surface = StreamDockSurface(transport)
    surface.attach("c1", 1)
    with pytest.raises(ConnectionError):
        await surface.show(1, b"png")
