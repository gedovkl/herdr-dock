"""Split agent slots into pages that fit the available keys."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from herdr_core.models import Agent, AgentStatus


@dataclass(frozen=True, slots=True)
class PageView:
    page: int
    page_count: int
    agents: tuple[Agent | None, ...]
    """One entry per agent key on this page; None for an empty key."""
    has_pager: bool
    """True when the last key is the pager instead of an agent."""
    offpage_statuses: frozenset[AgentStatus]


def paginate(slots: Sequence[Agent | None], capacity: int, page: int) -> PageView:
    """Lay out slots on `capacity` keys, using the last key as a pager when they don't fit.

    `page` wraps around, so callers can just add one to go to the next page.
    """
    if capacity < 2:
        raise ValueError(f"need at least 2 keys for agents, got {capacity}")
    if len(slots) <= capacity:
        per_page, page_count, has_pager = capacity, 1, False
    else:
        per_page = capacity - 1
        page_count = -(-len(slots) // per_page)
        has_pager = True
    page %= page_count
    start = page * per_page
    shown = tuple(slots[start : start + per_page])
    shown += (None,) * (per_page - len(shown))
    offpage = frozenset(
        agent.status
        for index, agent in enumerate(slots)
        if agent is not None and not start <= index < start + per_page
    )
    return PageView(page, page_count, shown, has_pager, offpage)
