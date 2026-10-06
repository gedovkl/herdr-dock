from pathlib import Path

import pytest

from herdr_core.client import HerdrSocketClient
from herdr_core.errors import HerdrProtocolError, HerdrRequestError, HerdrUnavailable
from herdr_core.events import FocusChanged, StatusChanged, TopologyChanged
from herdr_core.models import AgentStatus
from tests.fakes.herdr_server import FakeHerdrServer


def client_for(server: FakeHerdrServer, timeout: float = 2.0) -> HerdrSocketClient:
    return HerdrSocketClient(server.path, timeout=timeout)


async def test_list_agents(herdr_server: FakeHerdrServer) -> None:
    herdr_server.add_agent("w1:p1", "blocked")
    herdr_server.add_agent("w2:p1", "working")
    agents = await client_for(herdr_server).list_agents()
    assert [(a.pane_id, a.status) for a in agents] == [
        ("w1:p1", AgentStatus.BLOCKED),
        ("w2:p1", AgentStatus.WORKING),
    ]
    request = herdr_server.requests[0]
    assert request["method"] == "agent.list"
    assert isinstance(request["id"], str)  # herdr rejects non-string ids


async def test_request_ids_are_unique(herdr_server: FakeHerdrServer) -> None:
    client = client_for(herdr_server)
    await client.list_agents()
    await client.list_agents()
    assert herdr_server.requests[0]["id"] != herdr_server.requests[1]["id"]
    assert client.socket_path == herdr_server.path


async def test_focus_sends_target(herdr_server: FakeHerdrServer) -> None:
    herdr_server.add_agent("w1:p1")
    await client_for(herdr_server).focus_agent("w1:p1")
    assert herdr_server.requests[-1]["params"] == {"target": "w1:p1"}


async def test_error_reply_raises_request_error(herdr_server: FakeHerdrServer) -> None:
    with pytest.raises(HerdrRequestError) as info:
        await client_for(herdr_server).focus_agent("w9:p9")
    assert info.value.code == "agent_not_found"
    assert "w9:p9" in info.value.message


async def test_unreachable_socket(short_dir: Path) -> None:
    with pytest.raises(HerdrUnavailable, match="cannot connect"):
        await HerdrSocketClient(short_dir / "missing.sock").list_agents()


@pytest.mark.parametrize(
    ("raw", "error"),
    [
        (b"not json\n", HerdrProtocolError),
        (b"[1, 2]\n", HerdrProtocolError),
        (b'{"id": "x"}\n', HerdrProtocolError),
        (b'{"id": "x", "result": {"type": "agent_list"}}\n', HerdrProtocolError),
        (b"", HerdrUnavailable),
    ],
)
async def test_bad_replies(
    herdr_server: FakeHerdrServer, raw: bytes, error: type[Exception]
) -> None:
    herdr_server.raw_replies["agent.list"] = raw
    with pytest.raises(error):
        await client_for(herdr_server).list_agents()


async def test_entries_that_are_not_objects_are_skipped(herdr_server: FakeHerdrServer) -> None:
    herdr_server.raw_replies["agent.list"] = (
        b'{"id":"x","result":{"agents":[{"pane_id":"w1:p1"}, 7]}}\n'
    )
    agents = await client_for(herdr_server).list_agents()
    assert [a.pane_id for a in agents] == ["w1:p1"]


async def test_reply_timeout(herdr_server: FakeHerdrServer) -> None:
    herdr_server.silent.add("agent.list")
    with pytest.raises(HerdrUnavailable, match="read from herdr failed"):
        await client_for(herdr_server, timeout=0.05).list_agents()


async def test_subscribe_requests_status_per_pane_and_topology(
    herdr_server: FakeHerdrServer,
) -> None:
    stream = await client_for(herdr_server).subscribe({"w2:p1", "w1:p1"})
    try:
        subs = herdr_server.last_subscriptions()
        assert subs[:2] == [
            {"type": "pane.agent_status_changed", "pane_id": "w1:p1"},
            {"type": "pane.agent_status_changed", "pane_id": "w2:p1"},
        ]
        assert {"type": "workspace.closed"} in subs
        assert {"type": "pane.focused"} in subs
    finally:
        await stream.close()


async def test_stream_yields_typed_events(herdr_server: FakeHerdrServer) -> None:
    herdr_server.add_agent("w1:p1")
    stream = await client_for(herdr_server).subscribe({"w1:p1"})
    try:
        await herdr_server.set_status("w1:p1", "blocked")
        await herdr_server.emit("pane_focused", {"pane_id": "w1:p1"}, subscription="pane.focused")
        await herdr_server.emit("workspace_closed", {}, subscription="workspace.closed")
        assert await stream.next_event() == StatusChanged("w1:p1", AgentStatus.BLOCKED)
        assert await stream.next_event() == FocusChanged("w1:p1")
        assert await stream.next_event() == TopologyChanged("workspace_closed")
    finally:
        await stream.close()


async def test_stream_end_raises_unavailable(herdr_server: FakeHerdrServer) -> None:
    stream = await client_for(herdr_server).subscribe(set())
    await herdr_server.drop_subscribers()
    with pytest.raises(HerdrUnavailable):
        await stream.next_event()
    await stream.close()


async def test_subscribe_error_reply(herdr_server: FakeHerdrServer) -> None:
    herdr_server.errors["events.subscribe"] = ("invalid_request", "bad subscription")
    with pytest.raises(HerdrRequestError, match="bad subscription"):
        await client_for(herdr_server).subscribe(set())


async def test_subscribe_unexpected_reply(herdr_server: FakeHerdrServer) -> None:
    herdr_server.raw_replies["events.subscribe"] = b'{"id":"x","result":{"type":"ok"}}\n'
    with pytest.raises(HerdrProtocolError, match="unexpected subscribe reply"):
        await client_for(herdr_server).subscribe(set())
