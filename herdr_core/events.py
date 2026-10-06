"""Typed herdr subscription events and the parser that produces them."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from herdr_core.models import AgentStatus


@dataclass(frozen=True, slots=True)
class StatusChanged:
    pane_id: str
    status: AgentStatus


@dataclass(frozen=True, slots=True)
class FocusChanged:
    pane_id: str


@dataclass(frozen=True, slots=True)
class TopologyChanged:
    """Panes, tabs or workspaces appeared or went away, or an agent was detected/released."""

    reason: str


@dataclass(frozen=True, slots=True)
class UnknownEvent:
    name: str


HerdrEvent = StatusChanged | FocusChanged | TopologyChanged | UnknownEvent

# herdr mixes "pane.agent_status_changed" and "pane_created"; compare with dots normalised.
_TOPOLOGY_EVENTS = frozenset(
    {
        "pane_created",
        "pane_closed",
        "pane_exited",
        "pane_moved",
        "pane_agent_detected",
        "tab_closed",
        "tab_moved",
        "workspace_closed",
        "workspace_moved",
        "workspace_reordered",
    }
)

# Subscriptions requested in addition to the per-pane status ones.
TOPOLOGY_SUBSCRIPTIONS: tuple[str, ...] = (
    "pane.created",
    "pane.closed",
    "pane.exited",
    "pane.moved",
    "pane.agent_detected",
    "pane.focused",
    "tab.closed",
    "tab.moved",
    "workspace.closed",
    "workspace.moved",
    "workspace.reordered",
)


def parse_event(message: Mapping[str, Any]) -> HerdrEvent:
    name = str(message.get("event", ""))
    data = message.get("data")
    payload: Mapping[str, Any] = data if isinstance(data, Mapping) else {}
    key = name.replace(".", "_")
    pane_id = payload.get("pane_id")

    if key == "pane_agent_status_changed" and isinstance(pane_id, str):
        return StatusChanged(pane_id, AgentStatus.parse(payload.get("agent_status")))
    if key == "pane_focused" and isinstance(pane_id, str):
        return FocusChanged(pane_id)
    if key in _TOPOLOGY_EVENTS:
        return TopologyChanged(key)
    return UnknownEvent(name)
