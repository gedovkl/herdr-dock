"""Against a real, throwaway headless herdr session (never the user's own session).

Run with: scripts/test-integration.sh herdr_live
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import pytest

from herdr_core.client import HerdrSocketClient, SocketEventStream
from herdr_core.events import StatusChanged
from herdr_core.models import AgentStatus
from herdr_core.session import HerdrSession, SessionView
from tests.fakes.in_memory import RecordingRaiser

pytestmark = [
    pytest.mark.herdr_live,
    pytest.mark.skipif(shutil.which("herdr") is None, reason="herdr not installed"),
]


def _herdr(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["herdr", *args], capture_output=True, text=True, timeout=10, check=False)


@pytest.fixture(scope="module")
def herdr_socket() -> Iterator[Path]:
    name = f"herdr-dock-test-{os.getpid()}"
    server = subprocess.Popen(
        ["herdr", "--session", name, "server"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        socket = None
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and socket is None:
            status = _herdr("--session", name, "status", "server").stdout
            if "status: running" in status:
                socket = next(
                    Path(line.split(":", 1)[1].strip())
                    for line in status.splitlines()
                    if line.startswith("socket:")
                )
            else:
                time.sleep(0.1)
        if socket is None:
            pytest.fail("throwaway herdr server did not start")
        yield socket
    finally:
        _herdr("--session", name, "server", "stop")
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
        _herdr("session", "delete", name)


@pytest.fixture
async def client(herdr_socket: Path) -> AsyncIterator[HerdrSocketClient]:
    client = HerdrSocketClient(herdr_socket)
    yield client
    for workspace_id in {agent.workspace_id for agent in await client.list_agents()}:
        await client.request("workspace.close", {"workspace_id": workspace_id})


async def new_agent(client: HerdrSocketClient, status: str, cwd: str = "/tmp") -> str:
    workspace = await client.request("workspace.create", {"cwd": cwd})
    pane_id: str = workspace["root_pane"]["pane_id"]
    await report(client, pane_id, status)
    return pane_id


async def report(client: HerdrSocketClient, pane_id: str, status: str) -> None:
    params = {"pane_id": pane_id, "source": "herdr-dock-test", "agent": "claude", "state": status}
    await client.request("pane.report_agent", params)


async def test_list_reports_agents(client: HerdrSocketClient) -> None:
    pane_id = await new_agent(client, "working")
    (agent,) = [a for a in await client.list_agents() if a.pane_id == pane_id]
    assert agent.kind == "claude"
    assert agent.status is AgentStatus.WORKING
    assert Path(agent.cwd).resolve() == Path("/tmp").resolve()  # /tmp is a symlink on macOS


async def test_status_events_and_focus_mark_done_as_seen(client: HerdrSocketClient) -> None:
    pane_id = await new_agent(client, "working")
    stream = await client.subscribe({pane_id})
    try:
        await report(client, pane_id, "blocked")
        assert await _next_status(stream) == StatusChanged(pane_id, AgentStatus.BLOCKED)
        await report(client, pane_id, "idle")  # finished while unseen
        status = (await _next_status(stream)).status
        if status is AgentStatus.DONE:  # herdr 0.8: unseen completion; focusing marks it seen
            await client.focus_agent(pane_id)
            assert (await _next_status(stream)).status is AgentStatus.IDLE
        else:  # herdr 0.9 reports idle at once in a headless session
            assert status is AgentStatus.IDLE
    finally:
        await stream.close()


async def test_session_follows_real_herdr(client: HerdrSocketClient) -> None:
    views: list[SessionView] = []
    session = HerdrSession(client, client, RecordingRaiser(), capacity=14, on_view=views.append)
    await session.start()
    try:
        first = await new_agent(client, "idle")
        await _until(lambda: bool(views) and views[-1].total_agents == 1)
        second = await new_agent(client, "working", cwd="/")
        await _until(lambda: views[-1].total_agents == 2)
        await report(client, second, "blocked")
        await _until(lambda: AgentStatus.BLOCKED in views[-1].statuses)
        await session.press(1)
        await _until(lambda: _focused(views[-1]) == second)
        assert first != second
    finally:
        await session.stop()


def _focused(view: SessionView) -> str | None:
    return next((a.pane_id for a in view.page.agents if a and a.focused), None)


async def _next_status(stream: SocketEventStream) -> StatusChanged:
    while True:
        event = await asyncio.wait_for(stream.next_event(), 5)
        if isinstance(event, StatusChanged):
            return event


async def _until(predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0.02)

    await asyncio.wait_for(poll(), timeout)


async def test_focus_tab_moves_focus_to_that_agent(client: HerdrSocketClient) -> None:
    first = await new_agent(client, "idle")
    second = await new_agent(client, "idle", cwd="/")
    agents = {a.pane_id: a for a in await client.list_agents()}
    await client.focus_tab(agents[first].tab_id)
    assert {a.pane_id: a.focused for a in await client.list_agents()}[first]
    await client.focus_tab(agents[second].tab_id)
    focused = {a.pane_id: a.focused for a in await client.list_agents()}
    assert focused[second] and not focused[first]


async def test_tab_focus_keeps_the_pressed_pane_when_a_tab_has_two_agents(
    client: HerdrSocketClient,
) -> None:
    """A press sends agent.focus then tab.focus: the tab switch must not undo the pane choice."""
    first = await new_agent(client, "idle")
    split = await client.request(
        "pane.split", {"direction": "right", "target_pane_id": first, "focus": False}
    )
    second = split["pane"]["pane_id"]
    await report(client, second, "idle")
    agents = {a.pane_id: a for a in await client.list_agents()}
    assert agents[first].tab_id == agents[second].tab_id
    for target, other in ((second, first), (first, second)):
        await client.focus_agent(target)
        await client.focus_tab(agents[target].tab_id)
        focused = {a.pane_id: a.focused for a in await client.list_agents()}
        assert focused[target] and not focused[other], f"pressing {target}: {focused}"
