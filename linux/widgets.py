"""Live home-page keys: a clock and current weather (Open-Meteo, no API key)."""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
import urllib.request
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from herdr_core.faces import ClockFace, Face, WeatherFace

log = logging.getLogger(__name__)

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
FetchJson = Callable[[str], Awaitable[Any]]


class Widget(Protocol):
    def face(self) -> Face: ...


class ClockWidget:
    def __init__(
        self,
        time_format: str = "%H:%M",
        date_format: str = "%a %d %b",
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


def weather_symbol(code: int, is_day: bool = True) -> str:
    """WMO weather code → a glyph the bundled font has."""
    if code == 0:
        return "☀" if is_day else "☾"
    if code in (1, 2):
        return "☀" if is_day and code == 1 else "☁"
    if code == 3:
        return "☁"
    if code in (45, 48):
        return "≡"
    if 51 <= code <= 57:
        return "☂"
    if 61 <= code <= 67 or 80 <= code <= 82:
        return "☔"
    if 71 <= code <= 77 or code in (85, 86):
        return "❄"
    if code >= 95:
        return "⚡"
    return "?"


async def fetch_json(url: str, timeout: float = 10.0) -> Any:
    def get() -> Any:
        request = urllib.request.Request(url, headers={"User-Agent": "herdr-dock"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)

    return await asyncio.to_thread(get)


class WeatherWidget:
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
            return WeatherFace("--", "", self._place)
        unit = "°F" if self._units == "fahrenheit" else "°C"
        temperature = f"{round(self._reading.temperature)}{unit}"
        symbol = weather_symbol(self._reading.code, self._reading.is_day)
        return WeatherFace(temperature, symbol, self._place)

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
