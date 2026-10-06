"""In-memory fakes for the herdr_core ports."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Collection
from dataclasses import dataclass, field

from herdr_core.errors import HerdrError, HerdrRequestError, HerdrUnavailable
from herdr_core.events import FocusChanged, HerdrEvent, StatusChanged
from herdr_core.models import Agent, AgentStatus

_END = object()


class InMemoryStream:
    def __init__(self, pane_ids: Collection[str]) -> None:
        self.pane_ids = frozenset(pane_ids)
        self.closed = False
        self._queue: asyncio.Queue[object] = asyncio.Queue()

    def deliver(self, event: HerdrEvent) -> None:
        if isinstance(event, StatusChanged) and event.pane_id not in self.pane_ids:
            return
        self._queue.put_nowait(event)

    def end(self) -> None:
        self._queue.put_nowait(_END)

    async def next_event(self) -> HerdrEvent:
        item = await self._queue.get()
        if item is _END:
            raise HerdrUnavailable("stream ended")
        return item  # type: ignore[return-value]

    async def close(self) -> None:
        self.closed = True


@dataclass
class InMemoryHerdr:
    """Implements HerdrApi and HerdrEventSource without any I/O."""

    agents: dict[str, Agent] = field(default_factory=dict)
    focus_calls: list[str] = field(default_factory=list)
    streams: list[InMemoryStream] = field(default_factory=list)
    list_error: HerdrError | None = None
    subscribe_error: HerdrError | None = None
    list_calls: int = 0
    on_list: Callable[[], None] | None = None

    def add(self, pane_id: str, status: AgentStatus = AgentStatus.IDLE, **extra: object) -> Agent:
        workspace_id = pane_id.split(":", 1)[0]
        agent = Agent(
            pane_id=pane_id,
            workspace_id=workspace_id,
            tab_id=f"{workspace_id}:t1",
            kind="claude",
            status=status,
            cwd=f"/home/u/{workspace_id}",
            **extra,  # type: ignore[arg-type]
        )
        self.agents[pane_id] = agent
        return agent

    def push(self, event: HerdrEvent) -> None:
        if isinstance(event, StatusChanged) and event.pane_id in self.agents:
            self.agents[event.pane_id] = self.agents[event.pane_id].with_status(event.status)
        for stream in self.open_streams():
            stream.deliver(event)

    def end_streams(self) -> None:
        for stream in self.open_streams():
            stream.end()

    def open_streams(self) -> list[InMemoryStream]:
        return [stream for stream in self.streams if not stream.closed]

    async def list_agents(self) -> list[Agent]:
        self.list_calls += 1
        if self.on_list is not None:
            self.on_list()
        if self.list_error is not None:
            raise self.list_error
        return list(self.agents.values())

    async def focus_agent(self, pane_id: str) -> None:
        self.focus_calls.append(pane_id)
        agent = self.agents.get(pane_id)
        if agent is None:
            raise HerdrRequestError("agent_not_found", f"agent target {pane_id} not found")
        for key, other in self.agents.items():
            self.agents[key] = other.with_focus(key == pane_id)
        if agent.status == AgentStatus.DONE:
            self.push(StatusChanged(pane_id, AgentStatus.IDLE))
        self.push(FocusChanged(pane_id))

    async def subscribe(self, status_pane_ids: Collection[str]) -> InMemoryStream:
        if self.subscribe_error is not None:
            raise self.subscribe_error
        stream = InMemoryStream(status_pane_ids)
        self.streams.append(stream)
        return stream


@dataclass
class RecordingRaiser:
    raised: list[str] = field(default_factory=list)

    async def raise_window(self, agent: Agent) -> None:
        self.raised.append(agent.pane_id)
