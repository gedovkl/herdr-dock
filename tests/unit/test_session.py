from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

import pytest

from herdr_core.backoff import Backoff
from herdr_core.errors import HerdrRequestError, HerdrUnavailable
from herdr_core.events import FocusChanged, StatusChanged, TopologyChanged, UnknownEvent
from herdr_core.models import AgentStatus
from herdr_core.session import HerdrSession, SessionView
from tests.fakes.in_memory import InMemoryHerdr, RecordingRaiser
from tests.fakes.surface import FakeClock


@dataclass
class Views:
    seen: list[SessionView] = field(default_factory=list)
    _changed: asyncio.Event = field(default_factory=asyncio.Event)

    def __call__(self, view: SessionView) -> None:
        self.seen.append(view)
        self._changed.set()

    @property
    def last(self) -> SessionView:
        return self.seen[-1]

    async def wait_for(self, predicate: Callable[[SessionView], bool]) -> SessionView:
        async def until() -> SessionView:
            while not (self.seen and predicate(self.last)):
                self._changed.clear()
                await self._changed.wait()
            return self.last

        return await asyncio.wait_for(until(), 1.0)


def statuses(view: SessionView) -> list[str | None]:
    return [None if a is None else f"{a.pane_id}={a.status.value}" for a in view.page.agents]


@dataclass
class Sleeps:
    delays: list[float] = field(default_factory=list)

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        await asyncio.sleep(0)


@dataclass
class Rig:
    herdr: InMemoryHerdr
    raiser: RecordingRaiser
    views: Views
    sleeps: Sleeps
    session: HerdrSession


@pytest.fixture
async def rig() -> AsyncIterator[Rig]:
    herdr, raiser, views, sleeps = InMemoryHerdr(), RecordingRaiser(), Views(), Sleeps()
    session = HerdrSession(
        herdr, herdr, raiser, capacity=3, on_view=views, backoff=Backoff(0.5, 2, 4), sleep=sleeps
    )
    yield Rig(herdr, raiser, views, sleeps, session)
    await session.stop()


def connected(view: SessionView) -> bool:
    return view.connected


async def test_start_shows_offline_then_agents(rig: Rig) -> None:
    rig.herdr.add("w1:p1", AgentStatus.WORKING)
    await rig.session.start()
    view = await rig.views.wait_for(connected)
    assert not rig.views.seen[0].connected
    assert statuses(view) == ["w1:p1=working", None, None]
    assert view.total_agents == 1 and view.statuses == {AgentStatus.WORKING}
    assert rig.herdr.open_streams()[0].pane_ids == {"w1:p1"}


async def test_start_twice_is_harmless(rig: Rig) -> None:
    await rig.session.start()
    await rig.session.start()
    await rig.views.wait_for(connected)
    assert rig.session.running
    assert len(rig.herdr.streams) == 1


async def test_status_events_update_the_view(rig: Rig) -> None:
    rig.herdr.add("w1:p1")
    await rig.session.start()
    await rig.views.wait_for(connected)
    rig.herdr.push(StatusChanged("w1:p1", AgentStatus.BLOCKED))
    view = await rig.views.wait_for(lambda v: statuses(v)[0] == "w1:p1=blocked")
    assert view.statuses == {AgentStatus.BLOCKED}


async def test_new_agent_triggers_resubscribe(rig: Rig) -> None:
    rig.herdr.add("w1:p1")
    await rig.session.start()
    await rig.views.wait_for(connected)
    first = rig.herdr.open_streams()[0]
    rig.herdr.add("w2:p1", AgentStatus.WORKING)
    rig.herdr.push(TopologyChanged("pane_agent_detected"))
    view = await rig.views.wait_for(lambda v: v.total_agents == 2)
    assert statuses(view)[:2] == ["w1:p1=idle", "w2:p1=working"]
    assert first.closed
    assert rig.herdr.open_streams()[0].pane_ids == {"w1:p1", "w2:p1"}


async def test_status_for_unknown_pane_resyncs(rig: Rig) -> None:
    await rig.session.start()
    await rig.views.wait_for(connected)
    rig.herdr.add("w5:p1", AgentStatus.BLOCKED)
    # The current stream isn't subscribed to w5:p1, so deliver directly as herdr would after
    # a race between subscribe and the agent appearing.
    rig.herdr.open_streams()[0]._queue.put_nowait(StatusChanged("w5:p1", AgentStatus.BLOCKED))
    view = await rig.views.wait_for(lambda v: v.total_agents == 1)
    assert statuses(view)[0] == "w5:p1=blocked"


async def test_agent_that_appears_while_subscribing_is_picked_up(rig: Rig) -> None:
    rig.herdr.add("w1:p1")
    calls = {"n": 0}

    def appear_on_second_list() -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            rig.herdr.add("w2:p1")

    rig.herdr.on_list = appear_on_second_list
    await rig.session.start()
    view = await rig.views.wait_for(lambda v: v.connected and v.total_agents == 2)
    assert rig.herdr.open_streams()[-1].pane_ids == {"w1:p1", "w2:p1"}
    assert view.total_agents == 2


async def test_agent_set_that_never_settles_does_not_loop_forever(rig: Rig) -> None:
    counter = {"n": 0}

    def churn() -> None:
        counter["n"] += 1
        rig.herdr.add(f"w{counter['n']}:p1")

    rig.herdr.on_list = churn
    await rig.session.start()
    await rig.views.wait_for(connected)
    assert counter["n"] == 4  # one initial list + three resubscribe attempts


async def test_focus_events(rig: Rig) -> None:
    rig.herdr.add("w1:p1")
    rig.herdr.add("w2:p1")
    await rig.session.start()
    await rig.views.wait_for(connected)
    rig.herdr.push(FocusChanged("w2:p1"))
    view = await rig.views.wait_for(lambda v: any(a and a.focused for a in v.page.agents))
    assert [bool(a and a.focused) for a in view.page.agents] == [False, True, False]


async def test_replayed_focus_events_do_not_move_the_focus() -> None:
    """herdr replays old pane_focused events to new subscribers; agent.list is the truth."""
    herdr, views, clock = InMemoryHerdr(), Views(), FakeClock()
    session = HerdrSession(herdr, herdr, RecordingRaiser(), capacity=3, on_view=views, clock=clock)
    herdr.add("w1:p1", focused=True)
    herdr.add("w2:p1")
    await session.start()
    try:
        await views.wait_for(connected)
        lists = herdr.list_calls
        clock.now = 10.0
        for pane in ("w2:p1", "w9:p9", "w2:p1", "w1:p1", "w2:p1"):
            herdr.deliver(FocusChanged(pane))  # stale replay; real focus stays on w1:p1
        await _until(lambda: herdr.list_calls > lists)
        await _until(lambda: not herdr.open_streams()[0]._queue.qsize())
        for _ in range(20):
            await asyncio.sleep(0)
        assert herdr.list_calls == lists + 1  # one refresh for the whole burst
        focused = [a.pane_id for a in session.view.page.agents if a and a.focused]
        assert focused == ["w1:p1"]
        assert all(
            [a.pane_id for a in v.page.agents if a and a.focused] in ([], ["w1:p1"])
            for v in views.seen
        )
    finally:
        await session.stop()


async def test_focus_refresh_is_throttled_then_catches_up() -> None:
    herdr, views, clock = InMemoryHerdr(), Views(), FakeClock()
    session = HerdrSession(
        herdr,
        herdr,
        RecordingRaiser(),
        capacity=3,
        on_view=views,
        clock=clock,
        focus_refresh_interval=0.05,
    )
    herdr.add("w1:p1", focused=True)
    herdr.add("w2:p1")
    await session.start()
    try:
        await views.wait_for(connected)
        herdr.push(FocusChanged("w2:p1"))  # within the interval of the initial sync
        view = await views.wait_for(
            lambda v: [a.pane_id for a in v.page.agents if a and a.focused] == ["w2:p1"]
        )
        assert view.connected
    finally:
        await session.stop()


async def test_unknown_events_are_ignored(rig: Rig) -> None:
    rig.herdr.add("w1:p1")
    await rig.session.start()
    await rig.views.wait_for(connected)
    lists = rig.herdr.list_calls
    rig.herdr.push(UnknownEvent("pane_scroll_changed"))
    rig.herdr.push(StatusChanged("w1:p1", AgentStatus.DONE))
    await rig.views.wait_for(lambda v: statuses(v)[0] == "w1:p1=done")
    assert rig.herdr.list_calls == lists


async def test_press_focuses_and_raises(rig: Rig) -> None:
    rig.herdr.add("w1:p1", AgentStatus.DONE)
    await rig.session.start()
    await rig.views.wait_for(connected)
    await rig.session.press(0)
    assert rig.herdr.focus_calls == ["w1:p1"]
    assert rig.raiser.raised == ["w1:p1"]
    await rig.views.wait_for(lambda v: statuses(v)[0] == "w1:p1=idle")


async def test_press_on_empty_or_invalid_keys_does_nothing(rig: Rig) -> None:
    rig.herdr.add("w1:p1")
    await rig.session.start()
    await rig.views.wait_for(connected)
    for key in (1, 2, 3, -1, 99):
        await rig.session.press(key)
    assert rig.herdr.focus_calls == []


async def test_press_focus_failure_is_logged(rig: Rig, caplog: pytest.LogCaptureFixture) -> None:
    rig.herdr.add("w1:p1")
    await rig.session.start()
    await rig.views.wait_for(connected)
    del rig.herdr.agents["w1:p1"]  # gone in herdr, still shown on the key
    await rig.session.press(0)
    assert rig.raiser.raised == []
    assert "could not focus w1:p1" in caplog.text


async def test_pager_key_cycles_pages(rig: Rig) -> None:
    for n in range(1, 6):
        rig.herdr.add(f"w{n}:p1")
    await rig.session.start()
    view = await rig.views.wait_for(connected)
    assert view.page.has_pager and view.page.page_count == 3
    await rig.session.press(2)  # capacity 3: keys 0-1 agents, key 2 pager
    assert rig.views.last.page.page == 1
    assert statuses(rig.views.last) == ["w3:p1=idle", "w4:p1=idle"]
    await rig.session.press(2)
    await rig.session.press(2)
    assert rig.views.last.page.page == 0
    assert rig.herdr.focus_calls == []


async def test_reconnects_with_backoff_after_stream_ends(rig: Rig) -> None:
    rig.herdr.add("w1:p1")
    await rig.session.start()
    await rig.views.wait_for(connected)
    rig.herdr.list_error = HerdrUnavailable("down")
    rig.herdr.end_streams()
    await rig.views.wait_for(lambda v: not v.connected)
    await asyncio.wait_for(_until(lambda: len(rig.sleeps.delays) >= 3), 1.0)
    assert rig.sleeps.delays[:3] == [0.5, 1.0, 2.0]
    rig.herdr.list_error = None
    await rig.views.wait_for(connected)
    sleeps_before = len(rig.sleeps.delays)
    rig.herdr.end_streams()
    await rig.views.wait_for(lambda v: not v.connected)
    await rig.views.wait_for(connected)
    assert rig.sleeps.delays[sleeps_before] == 0.5  # backoff reset after a good connection


async def test_subscribe_failure_retries(rig: Rig) -> None:
    rig.herdr.subscribe_error = HerdrRequestError("invalid_request", "nope")
    await rig.session.start()
    await asyncio.wait_for(_until(lambda: len(rig.sleeps.delays) >= 1), 1.0)
    rig.herdr.subscribe_error = None
    await rig.views.wait_for(connected)


async def test_periodic_resync_catches_missed_changes() -> None:
    herdr, views = InMemoryHerdr(), Views()
    session = HerdrSession(
        herdr, herdr, RecordingRaiser(), capacity=3, on_view=views, resync_interval=0.01
    )
    herdr.add("w1:p1")
    await session.start()
    try:
        await views.wait_for(connected)
        herdr.agents["w1:p1"] = herdr.agents["w1:p1"].with_status(AgentStatus.BLOCKED)  # no event
        await views.wait_for(lambda v: statuses(v)[0] == "w1:p1=blocked")
    finally:
        await session.stop()


async def test_stop_disconnects_and_clears(rig: Rig) -> None:
    rig.herdr.add("w1:p1")
    await rig.session.start()
    await rig.views.wait_for(connected)
    await rig.session.stop()
    assert not rig.session.running
    assert rig.views.last.connected is False and rig.views.last.total_agents == 0
    assert all(stream.closed for stream in rig.herdr.streams)
    await rig.session.stop()  # idempotent


async def test_stream_close_errors_are_swallowed(rig: Rig) -> None:
    await rig.session.start()
    await rig.views.wait_for(connected)

    async def broken_close() -> None:
        raise OSError("already gone")

    rig.herdr.open_streams()[0].close = broken_close  # type: ignore[method-assign]
    await rig.session.stop()
    assert not rig.session.running


async def test_listener_errors_do_not_stop_the_session(caplog: pytest.LogCaptureFixture) -> None:
    herdr = InMemoryHerdr()
    herdr.add("w1:p1")
    calls: list[SessionView] = []

    def flaky(view: SessionView) -> None:
        calls.append(view)
        if len(calls) == 1:
            raise RuntimeError("boom")

    session = HerdrSession(herdr, herdr, RecordingRaiser(), capacity=3, on_view=flaky)
    await session.start()
    try:
        await asyncio.wait_for(_until(lambda: any(v.connected for v in calls)), 1.0)
    finally:
        await session.stop()
    assert "view listener failed" in caplog.text


def test_capacity_is_validated() -> None:
    herdr = InMemoryHerdr()
    with pytest.raises(ValueError):
        HerdrSession(herdr, herdr, RecordingRaiser(), capacity=1, on_view=lambda v: None)


async def _until(predicate: Callable[[], bool]) -> None:
    while not predicate():
        await asyncio.sleep(0)
