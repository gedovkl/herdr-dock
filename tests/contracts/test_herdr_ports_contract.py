"""Every HerdrApi/HerdrEventSource implementation must behave the same (LSP).

Runs against the in-memory fake and the real socket client talking to the fake server, so the
in-memory fake that session tests rely on can't drift from the real protocol behaviour.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from herdr_core.client import HerdrSocketClient
from herdr_core.errors import HerdrRequestError
from herdr_core.events import FocusChanged, StatusChanged
from herdr_core.models import AgentStatus
from tests.fakes.herdr_server import FakeHerdrServer
from tests.fakes.in_memory import InMemoryHerdr


@dataclass
class Harness:
    """A port implementation plus a way to seed agents and change their status from outside."""

    port: InMemoryHerdr | HerdrSocketClient
    add: Callable[[str, AgentStatus], None]
    set_status: Callable[[str, AgentStatus], Awaitable[None]]


@pytest.fixture(params=["in_memory", "socket"])
async def harness(request: pytest.FixtureRequest, short_dir: Path) -> AsyncIterator[Harness]:
    if request.param == "in_memory":
        fake = InMemoryHerdr()

        async def set_status_mem(pane_id: str, status: AgentStatus) -> None:
            fake.push(StatusChanged(pane_id, status))

        yield Harness(fake, lambda p, s: fake.add(p, s) and None, set_status_mem)
        return

    async with FakeHerdrServer(short_dir / "herdr.sock") as server:

        async def set_status_sock(pane_id: str, status: AgentStatus) -> None:
            await server.set_status(pane_id, status.value)

        yield Harness(
            HerdrSocketClient(server.path),
            lambda p, s: server.add_agent(p, s.value) and None,
            set_status_sock,
        )


async def test_lists_seeded_agents(harness: Harness) -> None:
    harness.add("w1:p1", AgentStatus.WORKING)
    harness.add("w2:p1", AgentStatus.BLOCKED)
    agents = await harness.port.list_agents()
    assert {(a.pane_id, a.status) for a in agents} == {
        ("w1:p1", AgentStatus.WORKING),
        ("w2:p1", AgentStatus.BLOCKED),
    }


async def test_focus_unknown_agent_raises(harness: Harness) -> None:
    with pytest.raises(HerdrRequestError) as info:
        await harness.port.focus_agent("w9:p9")
    assert info.value.code == "agent_not_found"


async def test_focus_marks_done_agent_seen(harness: Harness) -> None:
    harness.add("w1:p1", AgentStatus.DONE)
    stream = await harness.port.subscribe({"w1:p1"})
    try:
        await harness.port.focus_agent("w1:p1")
        assert await stream.next_event() == StatusChanged("w1:p1", AgentStatus.IDLE)
        assert await stream.next_event() == FocusChanged("w1:p1")
        (agent,) = await harness.port.list_agents()
        assert agent.focused and agent.status is AgentStatus.IDLE
    finally:
        await stream.close()


async def test_status_events_only_for_subscribed_panes(harness: Harness) -> None:
    harness.add("w1:p1", AgentStatus.IDLE)
    harness.add("w2:p1", AgentStatus.IDLE)
    stream = await harness.port.subscribe({"w2:p1"})
    try:
        await harness.set_status("w1:p1", AgentStatus.BLOCKED)
        await harness.set_status("w2:p1", AgentStatus.WORKING)
        assert await stream.next_event() == StatusChanged("w2:p1", AgentStatus.WORKING)
    finally:
        await stream.close()
