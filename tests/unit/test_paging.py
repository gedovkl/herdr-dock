import pytest

from herdr_core.models import Agent, AgentStatus
from herdr_core.paging import paginate


def agent(n: int, status: AgentStatus = AgentStatus.IDLE) -> Agent:
    return Agent(f"w{n}:p1", f"w{n}", f"w{n}:t1", "claude", status)


def test_everything_fits_without_pager() -> None:
    slots = [agent(1), None, agent(3)]
    view = paginate(slots, 4, 0)
    assert view.page_count == 1 and not view.has_pager
    assert view.agents == (agent(1), None, agent(3), None)
    assert view.offpage_statuses == frozenset()


def test_exactly_full_has_no_pager() -> None:
    view = paginate([agent(i) for i in range(4)], 4, 0)
    assert not view.has_pager and len(view.agents) == 4


def test_overflow_reserves_last_key_for_pager() -> None:
    slots = [agent(1), agent(2, AgentStatus.BLOCKED), agent(3), agent(4, AgentStatus.DONE)]
    first = paginate(slots, 3, 0)
    assert first.has_pager and first.page_count == 2
    assert first.agents == (agent(1), agent(2, AgentStatus.BLOCKED))
    assert first.offpage_statuses == {AgentStatus.IDLE, AgentStatus.DONE}

    second = paginate(slots, 3, 1)
    assert second.agents == (agent(3), agent(4, AgentStatus.DONE))
    assert second.offpage_statuses == {AgentStatus.IDLE, AgentStatus.BLOCKED}


def test_last_page_is_padded_and_page_wraps() -> None:
    slots = [agent(i) for i in range(5)]
    last = paginate(slots, 3, 2)
    assert last.agents == (agent(4), None)
    assert paginate(slots, 3, 3).page == 0
    assert paginate(slots, 3, -1).page == 2


def test_empty_slots_are_ignored_for_offpage_statuses() -> None:
    view = paginate([agent(1), agent(2), None, None], 3, 0)
    assert view.offpage_statuses == frozenset()


def test_capacity_must_leave_room_for_agent_and_pager() -> None:
    with pytest.raises(ValueError):
        paginate([], 1, 0)
