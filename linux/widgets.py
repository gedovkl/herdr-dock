"""Live home-page keys: a clock and current weather (Open-Meteo, no API key)."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import subprocess
import time
import urllib.parse
import urllib.request
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from herdr_core.faces import ClockFace, Face, PomodoroFace, TimerFace, WeatherFace

log = logging.getLogger(__name__)

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
FetchJson = Callable[[str], Awaitable[Any]]


class Widget(Protocol):
    def face(self) -> Face: ...

    def press(self) -> bool:
        """Handle a key press; False if the key's run/app/focus should run instead."""
        ...

    def advance(self) -> None:
        """Called every tick, even when the key isn't visible (e.g. phase notifications)."""
        ...


Notify = Callable[[str, str], None]


def desktop_notify(title: str, body: str) -> None:
    """Best-effort desktop notification (notify-send); never raises."""
    try:
        subprocess.Popen(
            ["notify-send", "--app-name=herdr-dock", title, body],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        log.info("notify-send unavailable: %s", exc)


def format_duration(seconds: float) -> str:
    """m:ss, or h:mm:ss from one hour."""
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


class _Passive:
    """Display-only widget: presses fall through to the key's run/app/focus."""

    def press(self) -> bool:
        return False

    def advance(self) -> None:
        return None


class PomodoroWidget:
    """Press to start (work), press again to stop. Alternates work and rest while running."""

    def __init__(
        self,
        work_seconds: float = 25 * 60,
        rest_seconds: float = 5 * 60,
        *,
        clock: Callable[[], float] = time.monotonic,
        notify: Notify | None = None,
    ) -> None:
        if work_seconds <= 0 or rest_seconds <= 0:
            raise ValueError("pomodoro work and rest must be positive")
        self._work = work_seconds
        self._rest = rest_seconds
        self._clock = clock
        self._notify = notify
        self._started: float | None = None
        self._phase = "idle"

    @property
    def running(self) -> bool:
        return self._started is not None

    def press(self) -> bool:
        if self._started is None:
            self._started, self._phase = self._clock(), "work"
            log.info("pomodoro started")
        else:
            self._started, self._phase = None, "idle"
            log.info("pomodoro stopped")
        return True

    def _state(self) -> tuple[str, float, float]:
        """(phase, seconds remaining, progress) right now."""
        assert self._started is not None
        position = (self._clock() - self._started) % (self._work + self._rest)
        if position < self._work:
            return "work", self._work - position, position / self._work
        position -= self._work
        return "rest", self._rest - position, position / self._rest

    def face(self) -> Face:
        if self._started is None:
            return PomodoroFace()
        phase, remaining, progress = self._state()
        # Round up so a fresh 25-minute phase shows 25:00, not 24:59.
        return PomodoroFace(phase, format_duration(math.ceil(remaining)), round(progress, 2))

    def advance(self) -> None:
        if self._started is None:
            return
        phase = self._state()[0]
        if phase == self._phase:
            return
        self._phase = phase
        if self._notify is not None:
            if phase == "rest":
                self._notify("Pomodoro: rest", f"Take a {format_duration(self._rest)} break")
            else:
                self._notify("Pomodoro: work", f"Focus for {format_duration(self._work)}")


class TimerWidget:
    """A stopwatch: press to start, press again to stop."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._started: float | None = None

    @property
    def running(self) -> bool:
        return self._started is not None

    def press(self) -> bool:
        if self._started is None:
            self._started = self._clock()
        else:
            log.info("timer stopped at %s", format_duration(self._clock() - self._started))
            self._started = None
        return True

    def face(self) -> Face:
        if self._started is None:
            return TimerFace()
        elapsed = self._clock() - self._started
        return TimerFace(format_duration(elapsed), pulse=int(elapsed) % 2 == 0)

    def advance(self) -> None:
        return None


class ClockWidget(_Passive):
    def __init__(
        self,
        time_format: str = "%H:%M",
        date_format: str = "%a\n%-d %b",
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._time_format = time_format
        self._date_format = date_format
        self._now = now

    def face(self) -> Face:
        now = self._now()
        date = now.strftime(self._date_format) if self._date_format else ""
        return ClockFace(now.strftime(self._time_format), date)


@dataclass(frozen=True, slots=True)
class WeatherReading:
    temperature: float
    code: int
    is_day: bool


def weather_condition(code: int, is_day: bool = True) -> str:
    """WMO weather code → a theme.WEATHER_SYMBOL condition name."""
    if code in (0, 1):  # clear, mainly clear
        return "sun" if is_day else "moon"
    if code in (2, 3):  # partly cloudy, overcast
        return "cloud"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 57:
        return "drizzle"
    if 61 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if code >= 95:
        return "thunder"
    return "unknown"


async def fetch_json(url: str, timeout: float = 10.0) -> Any:
    def get() -> Any:
        request = urllib.request.Request(url, headers={"User-Agent": "herdr-dock"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)

    return await asyncio.to_thread(get)


class WeatherWidget(_Passive):
    """Shows the last successful reading; refresh() fetches a new one."""

    RETRY_SECONDS = 60

    def __init__(
        self,
        latitude: float,
        longitude: float,
        *,
        units: str = "celsius",
        place: str = "",
        refresh_seconds: float = 15 * 60,
        fetch: FetchJson = fetch_json,
    ) -> None:
        self.refresh_seconds = refresh_seconds
        self._latitude = latitude
        self._longitude = longitude
        self._units = units
        self._place = place
        self._fetch = fetch
        self._reading: WeatherReading | None = None
        self._failing = False

    @property
    def url(self) -> str:
        query = urllib.parse.urlencode(
            {
                "latitude": self._latitude,
                "longitude": self._longitude,
                "current": "temperature_2m,weather_code,is_day",
                "temperature_unit": self._units,
                "timezone": "auto",
            }
        )
        return f"{OPEN_METEO}?{query}"

    def face(self) -> Face:
        if self._reading is None:
            return WeatherFace("--", place=self._place)
        value = self._reading.temperature
        fahrenheit = self._units == "fahrenheit"
        temperature = f"{round(value)}{'°F' if fahrenheit else '°C'}"
        celsius = (value - 32) * 5 / 9 if fahrenheit else value
        condition = weather_condition(self._reading.code, self._reading.is_day)
        return WeatherFace(temperature, condition, self._place, round(celsius, 1))

    async def refresh(self) -> bool:
        """Fetch current conditions. False (and the old reading kept) on any failure."""
        try:
            data = await self._fetch(self.url)
            current = data["current"]
            reading = WeatherReading(
                float(current["temperature_2m"]),
                int(current["weather_code"]),
                bool(current.get("is_day", 1)),
            )
        except Exception as exc:
            if not self._failing:
                log.warning("weather update failed (keeping the last reading): %s", exc)
                self._failing = True
            return False
        if self._failing:
            log.info("weather updates working again")
        self._failing = False
        self._reading = reading
        return True
