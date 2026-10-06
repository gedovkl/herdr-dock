from herdr_core.models import Agent, AgentStatus
from herdr_core.store import AgentStore, natural_key


def agent(pane_id: str, status: AgentStatus = AgentStatus.IDLE, **kw: object) -> Agent:
    workspace_id = pane_id.split(":")[0]
    return Agent(pane_id, workspace_id, f"{workspace_id}:t1", "claude", status, **kw)  # type: ignore[arg-type]


def ids(store: AgentStore) -> list[str | None]:
    return [None if a is None else a.pane_id for a in store.slots()]


def test_natural_key_orders_numbers_numerically() -> None:
    assert sorted(["w10:p1", "w9:p1", "w9:p10", "w9:p2"], key=natural_key) == [
        "w9:p1",
        "w9:p2",
        "w9:p10",
        "w10:p1",
    ]


def test_first_load_uses_herdr_order() -> None:
    store = AgentStore()
    assert store.replace([agent("w10:p1"), agent("w2:p3"), agent("w2:p1")])
    assert ids(store) == ["w2:p1", "w2:p3", "w10:p1"]


def test_existing_agents_keep_their_slots_and_newcomers_fill_gaps() -> None:
    store = AgentStore()
    store.replace([agent("w1:p1"), agent("w2:p1"), agent("w3:p1")])
    store.replace([agent("w1:p1"), agent("w3:p1")])
    assert ids(store) == ["w1:p1", None, "w3:p1"]
    store.replace([agent("w1:p1"), agent("w3:p1"), agent("w9:p1"), agent("w0:p1")])
    assert ids(store) == ["w1:p1", "w0:p1", "w3:p1", "w9:p1"]


def test_trailing_gaps_are_trimmed() -> None:
    store = AgentStore()
    store.replace([agent("w1:p1"), agent("w2:p1")])
    store.replace([agent("w1:p1")])
    assert ids(store) == ["w1:p1"]
    store.replace([])
    assert ids(store) == []


def test_replace_reports_changes_only() -> None:
    store = AgentStore()
    assert not store.replace([])
    store.replace([agent("w1:p1")])
    assert not store.replace([agent("w1:p1")])
    assert store.replace([agent("w1:p1", AgentStatus.WORKING)])


def test_apply_status() -> None:
    store = AgentStore()
    store.replace([agent("w1:p1")])
    assert store.apply_status("w1:p1", AgentStatus.BLOCKED)
    assert not store.apply_status("w1:p1", AgentStatus.BLOCKED)
    assert not store.apply_status("w5:p5", AgentStatus.BLOCKED)
    slot = store.slots()[0]
    assert slot is not None and slot.status is AgentStatus.BLOCKED


def test_apply_focus_moves_the_flag() -> None:
    store = AgentStore()
    store.replace([agent("w1:p1", focused=True), agent("w2:p1")])
    assert store.apply_focus("w2:p1")
    assert [a.focused for a in store.slots() if a] == [False, True]
    assert not store.apply_focus("w2:p1")
    assert store.apply_focus("w9:p9")  # a non-agent pane took focus
    assert not any(a.focused for a in store.slots() if a)


def test_has_and_pane_ids() -> None:
    store = AgentStore()
    store.replace([agent("w1:p1"), agent("w2:p1")])
    assert store.has("w1:p1") and not store.has("w3:p1")
    assert store.pane_ids() == {"w1:p1", "w2:p1"}
