import pytest

from herdr_core.events import (
    FocusChanged,
    StatusChanged,
    TopologyChanged,
    UnknownEvent,
    parse_event,
)
from herdr_core.models import AgentStatus


def test_status_changed_uses_dotted_name_as_herdr_sends_it() -> None:
    message = {
        "event": "pane.agent_status_changed",
        "data": {"pane_id": "w2:p1", "agent_status": "blocked", "agent": "claude"},
    }
    assert parse_event(message) == StatusChanged("w2:p1", AgentStatus.BLOCKED)


def test_status_changed_also_accepts_underscore_name() -> None:
    message = {"event": "pane_agent_status_changed", "data": {"pane_id": "w1:p1"}}
    assert parse_event(message) == StatusChanged("w1:p1", AgentStatus.UNKNOWN)


def test_focus() -> None:
    message = {"event": "pane_focused", "data": {"pane_id": "w1:p2", "type": "pane_focused"}}
    assert parse_event(message) == FocusChanged("w1:p2")


@pytest.mark.parametrize(
    "name",
    ["pane_created", "pane_closed", "pane_exited", "pane_agent_detected", "workspace_closed"],
)
def test_topology_events(name: str) -> None:
    assert parse_event({"event": name, "data": {"pane_id": "w1:p1"}}) == TopologyChanged(name)


@pytest.mark.parametrize(
    "message",
    [
        {"event": "pane_scroll_changed", "data": {}},
        {"event": "pane.agent_status_changed", "data": {"agent_status": "idle"}},
        {"event": "pane_focused", "data": "not a mapping"},
        {},
    ],
)
def test_unknown_or_incomplete_events(message: dict[str, object]) -> None:
    assert isinstance(parse_event(message), UnknownEvent)
