"""HerdrSession: keeps agent keys in sync with herdr while Herdr mode is active."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass

from herdr_core.backoff import Backoff
from herdr_core.errors import HerdrError
from herdr_core.events import FocusChanged, HerdrEvent, StatusChanged, TopologyChanged
from herdr_core.models import AgentStatus
from herdr_core.paging import PageView, paginate
from herdr_core.ports import EventStream, HerdrApi, HerdrEventSource, Raiser, Sleep
from herdr_core.store import AgentStore

log = logging.getLogger(__name__)

# How often to retry resubscribing while the agent set keeps changing underneath us.
_RESUBSCRIBE_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class SessionView:
    connected: bool
    page: PageView
    total_agents: int
    statuses: frozenset[AgentStatus]
    """Every status present across all agents, for summary keys (Exit, pager)."""


ViewListener = Callable[[SessionView], None]


class HerdrSession:
    """Owns the herdr connection for one front end.

    `start()` connects and follows events until `stop()`. Every visible change is pushed to
    `on_view`. Key presses come back in through `press(key_index)`, where index 0 is the first
    agent key and index `capacity - 1` is the pager when one is shown.
    """

    def __init__(
        self,
        api: HerdrApi,
        events: HerdrEventSource,
        raiser: Raiser,
        *,
        capacity: int,
        on_view: ViewListener,
        resync_interval: float = 30.0,
        backoff: Backoff | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        paginate((), capacity, 0)  # validates capacity early
        self._api = api
        self._events = events
        self._raiser = raiser
        self._capacity = capacity
        self._on_view = on_view
        self._resync_interval = resync_interval
        self._backoff = backoff or Backoff()
        self._sleep = sleep
        self._store = AgentStore()
        self._page = 0
        self._connected = False
        self._stream: EventStream | None = None
        self._subscribed: frozenset[str] | None = None
        self._task: asyncio.Task[None] | None = None
        self._last_view: SessionView | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def view(self) -> SessionView:
        slots = self._store.slots()
        agents = [agent for agent in slots if agent is not None]
        return SessionView(
            connected=self._connected,
            page=paginate(slots, self._capacity, self._page),
            total_agents=len(agents),
            statuses=frozenset(agent.status for agent in agents),
        )

    async def start(self) -> None:
        if self.running:
            return
        self._task = asyncio.create_task(self._run(), name="herdr-session")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._connected = False
        self._store = AgentStore()
        self._emit()

    async def press(self, key_index: int) -> None:
        page = self.view.page
        if page.has_pager and key_index == len(page.agents):
            self.next_page()
            return
        if not 0 <= key_index < len(page.agents):
            return
        agent = page.agents[key_index]
        if agent is None:
            return
        try:
            await self._api.focus_agent(agent.pane_id)
        except HerdrError as exc:
            log.warning("could not focus %s: %s", agent.pane_id, exc)
            return
        await self._raiser.raise_window(agent)

    def next_page(self) -> None:
        self._page = paginate(self._store.slots(), self._capacity, self._page + 1).page
        self._emit()

    async def _run(self) -> None:
        self._emit()
        try:
            while True:
                try:
                    await self._follow()
                except HerdrError as exc:
                    log.info("herdr connection lost: %s", exc)
                await self._drop_stream()
                self._connected = False
                self._emit()
                await self._sleep(self._backoff.next_delay())
        finally:
            await self._drop_stream()

    async def _follow(self) -> None:
        await self._sync()
        self._connected = True
        self._backoff.reset()
        self._emit()
        while True:
            assert self._stream is not None
            try:
                event = await asyncio.wait_for(self._stream.next_event(), self._resync_interval)
            except TimeoutError:
                await self._sync()
            else:
                await self._handle(event)
            self._emit()

    async def _handle(self, event: HerdrEvent) -> None:
        if isinstance(event, StatusChanged):
            if not self._store.apply_status(event.pane_id, event.status) and not self._store.has(
                event.pane_id
            ):
                await self._sync()
        elif isinstance(event, FocusChanged):
            self._store.apply_focus(event.pane_id)
        elif isinstance(event, TopologyChanged):
            await self._sync()

    async def _sync(self) -> None:
        """Refresh all agents, and resubscribe if the set of agent panes changed."""
        self._store.replace(await self._api.list_agents())
        for _ in range(_RESUBSCRIBE_ATTEMPTS):
            wanted = self._store.pane_ids()
            if wanted == self._subscribed:
                return
            stream = await self._events.subscribe(wanted)
            await self._drop_stream()
            self._stream, self._subscribed = stream, wanted
            # Anything that changed while subscribing is caught by listing again.
            self._store.replace(await self._api.list_agents())
        log.debug("agent set still changing after resubscribing; next event will catch up")

    async def _drop_stream(self) -> None:
        stream, self._stream, self._subscribed = self._stream, None, None
        if stream is not None:
            try:
                await stream.close()
            except Exception:
                log.debug("error closing event stream", exc_info=True)

    def _emit(self) -> None:
        view = self.view
        if view == self._last_view:
            return
        self._last_view = view
        try:
            self._on_view(view)
        except Exception:
            log.exception("view listener failed")
