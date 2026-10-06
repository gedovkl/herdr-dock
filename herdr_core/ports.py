"""Interfaces herdr_core depends on. Adapters implement them; tests fake them."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection, Sequence
from typing import Protocol

from herdr_core.events import HerdrEvent
from herdr_core.models import Agent


class HerdrApi(Protocol):
    async def list_agents(self) -> Sequence[Agent]: ...

    async def focus_agent(self, pane_id: str) -> None: ...

    async def focus_tab(self, tab_id: str) -> None:
        """Switch to a tab. herdr 0.9's attached UIs follow this, but not `focus_agent`."""
        ...


class EventStream(Protocol):
    async def next_event(self) -> HerdrEvent:
        """Next event; raises HerdrUnavailable when the stream ends."""
        ...

    async def close(self) -> None: ...


class HerdrEventSource(Protocol):
    async def subscribe(self, status_pane_ids: Collection[str]) -> EventStream:
        """Open a stream with status events for these panes plus all topology events."""
        ...


class KeySurface(Protocol):
    """Somewhere key images go: the M18 via the Device SDK, or the StreamDock app."""

    async def show(self, key: int, png: bytes) -> None: ...


class Raiser(Protocol):
    async def raise_window(self, agent: Agent) -> None: ...


Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]
