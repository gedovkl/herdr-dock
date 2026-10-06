"""What each key shows, independent of pixels: SessionView → per-key Face value objects."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from herdr_core.models import AgentStatus, LabelStyle
from herdr_core.session import SessionView
from herdr_core.theme import STATUS_PRIORITY


@dataclass(frozen=True, slots=True)
class EmptyFace:
    pass


@dataclass(frozen=True, slots=True)
class OfflineFace:
    pass


@dataclass(frozen=True, slots=True)
class AgentFace:
    kind: str
    label: str
    status: AgentStatus
    focused: bool = False


@dataclass(frozen=True, slots=True)
class PagerFace:
    page: int
    page_count: int
    offpage: tuple[AgentStatus, ...]
    """Statuses on other pages, most urgent first."""


@dataclass(frozen=True, slots=True)
class ExitFace:
    statuses: tuple[AgentStatus, ...]
    """Statuses across all agents, most urgent first."""
    connected: bool = True


@dataclass(frozen=True, slots=True)
class LauncherFace:
    """A home-page key: an icon image or a large symbol, with a label underneath."""

    label: str
    symbol: str = ""
    icon: str = ""
    """Path to an image file; takes precedence over the symbol."""


@dataclass(frozen=True, slots=True)
class ClockFace:
    """Large time with the date underneath (already formatted)."""

    time: str
    date: str = ""


@dataclass(frozen=True, slots=True)
class WeatherFace:
    """Current conditions. The renderer picks the glyph and colours from `condition`/`celsius`."""

    temperature: str
    """Formatted for display, in the configured units (e.g. "52°F")."""
    condition: str = ""
    """One of theme.WEATHER_SYMBOL's keys (sun, moon, cloud, fog, drizzle, rain, snow, thunder)."""
    place: str = ""
    celsius: float | None = None
    """The temperature in °C, for colouring; None before the first reading."""


@dataclass(frozen=True, slots=True)
class PomodoroFace:
    """Stopped: a tomato. Running: phase, time left and progress through the phase."""

    phase: str = "idle"
    """"idle", "work" or "rest"."""
    remaining: str = ""
    progress: float = 0.0
    """0.0 → 1.0 through the current phase."""


@dataclass(frozen=True, slots=True)
class TimerFace:
    """Stopped: a stopwatch icon. Running: the elapsed time."""

    elapsed: str = ""
    """Empty while stopped."""
    pulse: bool = False
    """Alternates every second while running (a blinking dot)."""


Face = (
    EmptyFace
    | OfflineFace
    | AgentFace
    | PagerFace
    | ExitFace
    | LauncherFace
    | ClockFace
    | WeatherFace
    | PomodoroFace
    | TimerFace
)


@dataclass(frozen=True, slots=True)
class KeyLayout:
    """Maps physical key indexes to the Exit key and session key indexes.

    With `exit_key`, key 0 is Exit and keys 1.. are the session's agent/pager keys.
    """

    exit_key: bool = True

    def is_exit(self, key: int) -> bool:
        return self.exit_key and key == 0

    def session_index(self, key: int) -> int:
        return key - 1 if self.exit_key else key

    def session_capacity(self, key_count: int) -> int:
        return key_count - 1 if self.exit_key else key_count


def by_priority(statuses: Iterable[AgentStatus]) -> tuple[AgentStatus, ...]:
    present = set(statuses)
    return tuple(status for status in STATUS_PRIORITY if status in present)


def faces_for(view: SessionView, label: LabelStyle, layout: KeyLayout) -> tuple[Face, ...]:
    page = view.page
    session_keys = len(page.agents) + (1 if page.has_pager else 0)
    faces: list[Face] = []
    if layout.exit_key:
        faces.append(ExitFace(by_priority(view.statuses), view.connected))
    if not view.connected:
        faces.extend(OfflineFace() for _ in range(session_keys))
        return tuple(faces)
    for agent in page.agents:
        if agent is None:
            faces.append(EmptyFace())
        else:
            faces.append(AgentFace(agent.kind, agent.label(label), agent.status, agent.focused))
    if page.has_pager:
        faces.append(PagerFace(page.page, page.page_count, by_priority(page.offpage_statuses)))
    return tuple(faces)
