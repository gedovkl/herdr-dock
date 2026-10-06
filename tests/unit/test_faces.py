from herdr_core.faces import (
    AgentFace,
    EmptyFace,
    ExitFace,
    KeyLayout,
    OfflineFace,
    PagerFace,
    by_priority,
    faces_for,
)
from herdr_core.models import Agent, AgentStatus
from herdr_core.paging import paginate
from herdr_core.session import SessionView

S = AgentStatus


def agent(n: int, status: AgentStatus, focused: bool = False) -> Agent:
    return Agent(f"w{n}:p1", f"w{n}", f"w{n}:t1", "claude", status, cwd=f"/p/a{n}", focused=focused)


def view(
    slots: list[Agent | None], capacity: int, connected: bool = True, page: int = 0
) -> SessionView:
    agents = [a for a in slots if a]
    return SessionView(
        connected, paginate(slots, capacity, page), len(agents), frozenset(a.status for a in agents)
    )


def test_by_priority_orders_like_herdr() -> None:
    assert by_priority([S.IDLE, S.BLOCKED, S.WORKING, S.IDLE]) == (S.BLOCKED, S.WORKING, S.IDLE)


def test_exit_then_agents_and_empty_keys() -> None:
    faces = faces_for(view([agent(1, S.BLOCKED, True), None], 3), "cwd", KeyLayout())
    assert faces == (
        ExitFace((S.BLOCKED,)),
        AgentFace("claude", "a1", S.BLOCKED, True),
        EmptyFace(),
        EmptyFace(),
    )


def test_pager_face_when_overflowing() -> None:
    slots = [agent(1, S.IDLE), agent(2, S.DONE), agent(3, S.BLOCKED)]
    faces = faces_for(view(slots, 2, page=1), "cwd", KeyLayout(exit_key=False))
    assert faces == (AgentFace("claude", "a2", S.DONE), PagerFace(1, 3, (S.BLOCKED, S.IDLE)))


def test_offline_fills_every_session_key() -> None:
    faces = faces_for(view([], 3, connected=False), "cwd", KeyLayout())
    assert faces == (ExitFace((), connected=False), OfflineFace(), OfflineFace(), OfflineFace())


def test_layout_mapping() -> None:
    with_exit, without = KeyLayout(), KeyLayout(exit_key=False)
    assert with_exit.is_exit(0) and not with_exit.is_exit(1)
    assert not without.is_exit(0)
    assert with_exit.session_index(1) == 0 and without.session_index(1) == 1
    assert with_exit.session_capacity(15) == 14 and without.session_capacity(15) == 15
