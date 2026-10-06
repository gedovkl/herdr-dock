"""Agent state with stable key slots."""

from __future__ import annotations

import re
from collections.abc import Iterable

from herdr_core.models import Agent, AgentStatus

_DIGITS = re.compile(r"(\d+)")


def natural_key(text: str) -> tuple[tuple[int, int | str], ...]:
    """Sort key where "w10" comes after "w9"."""
    return tuple(
        (1, int(part)) if part.isdigit() else (0, part) for part in _DIGITS.split(text) if part
    )


def herdr_order(agent: Agent) -> tuple[tuple[tuple[int, int | str], ...], ...]:
    return (natural_key(agent.workspace_id), natural_key(agent.tab_id), natural_key(agent.pane_id))


class AgentStore:
    """Agents by pane, each holding a stable slot until it goes away.

    New agents fill the lowest free slot in herdr order, so existing keys never reshuffle.
    """

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}
        self._slots: list[str | None] = []

    def replace(self, agents: Iterable[Agent]) -> bool:
        """Make the store match a full agent list. Returns True if anything changed."""
        incoming = {agent.pane_id: agent for agent in agents}
        before = self.slots()

        for index, pane_id in enumerate(self._slots):
            if pane_id is not None and pane_id not in incoming:
                self._slots[index] = None
        newcomers = sorted(
            (agent for pane_id, agent in incoming.items() if pane_id not in self._agents),
            key=herdr_order,
        )
        self._agents = incoming
        for agent in newcomers:
            self._place(agent.pane_id)
        self._trim()
        return self.slots() != before

    def apply_status(self, pane_id: str, status: AgentStatus) -> bool:
        agent = self._agents.get(pane_id)
        if agent is None or agent.status == status:
            return False
        self._agents[pane_id] = agent.with_status(status)
        return True

    def apply_focus(self, pane_id: str) -> bool:
        changed = False
        for key, agent in self._agents.items():
            focused = key == pane_id
            if agent.focused != focused:
                self._agents[key] = agent.with_focus(focused)
                changed = True
        return changed

    def has(self, pane_id: str) -> bool:
        return pane_id in self._agents

    def pane_ids(self) -> frozenset[str]:
        return frozenset(self._agents)

    def slots(self) -> tuple[Agent | None, ...]:
        return tuple(None if pane_id is None else self._agents[pane_id] for pane_id in self._slots)

    def _place(self, pane_id: str) -> None:
        for index, occupant in enumerate(self._slots):
            if occupant is None:
                self._slots[index] = pane_id
                return
        self._slots.append(pane_id)

    def _trim(self) -> None:
        while self._slots and self._slots[-1] is None:
            self._slots.pop()
