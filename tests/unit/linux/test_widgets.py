from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from herdr_core.faces import ClockFace, PomodoroFace, TimerFace, WeatherFace
from linux.widgets import (
    ClockWidget,
    PomodoroWidget,
    TimerWidget,
    WeatherWidget,
    desktop_notify,
    fetch_json,
    format_duration,
    weather_condition,
)

NASHUA = (42.7654, -71.4676)
GOOD = {"current": {"temperature_2m": 51.6, "weather_code": 0, "is_day": 1}}


def test_clock_formats_time_and_date() -> None:
    now = datetime(2026, 10, 5, 14, 7, 59)
    assert ClockWidget(now=lambda: now).face() == ClockFace("14:07", "Mon\n5 Oct")  # 2 rows
    assert ClockWidget("%H:%M:%S", "", now=lambda: now).face() == ClockFace("14:07:59", "")


@pytest.mark.parametrize(
    ("code", "is_day", "condition"),
    [
        (0, True, "sun"),
        (0, False, "moon"),
        (1, True, "sun"),
        (1, False, "moon"),  # "mainly clear" at night
        (2, False, "cloud"),
        (2, True, "cloud"),
        (3, True, "cloud"),
        (45, True, "fog"),
        (55, True, "drizzle"),
        (63, True, "rain"),
        (81, True, "rain"),
        (75, True, "snow"),
        (86, True, "snow"),
        (95, True, "thunder"),
        (99, True, "thunder"),
        (17, True, "unknown"),
    ],
)
def test_weather_conditions(code: int, is_day: bool, condition: str) -> None:
    assert weather_condition(code, is_day) == condition


class Fetcher:
    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.urls: list[str] = []

    async def __call__(self, url: str) -> Any:
        self.urls.append(url)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


async def test_weather_reading_in_configured_units() -> None:
    fetch = Fetcher(GOOD)
    widget = WeatherWidget(*NASHUA, units="fahrenheit", place="Nashua", fetch=fetch)
    assert widget.face() == WeatherFace("--", place="Nashua")  # nothing fetched yet
    assert await widget.refresh()
    assert widget.face() == WeatherFace("52°F", "sun", "Nashua", 10.9)  # °C kept for colour
    assert "latitude=42.7654" in fetch.urls[0] and "longitude=-71.4676" in fetch.urls[0]
    assert "temperature_unit=fahrenheit" in fetch.urls[0]
    snowy = {"current": {"temperature_2m": -0.4, "weather_code": 71}}
    celsius = WeatherWidget(*NASHUA, fetch=Fetcher(snowy))
    await celsius.refresh()
    assert celsius.face() == WeatherFace("0°C", "snow", "", -0.4)  # no "-0" shown


async def test_failed_refresh_keeps_last_reading_and_logs_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")
    fetch = Fetcher(GOOD, OSError("offline"), {"bad": "shape"}, GOOD)
    widget = WeatherWidget(*NASHUA, units="fahrenheit", fetch=fetch)
    assert await widget.refresh()
    assert not await widget.refresh()
    assert not await widget.refresh()
    assert widget.face().temperature == "52°F"  # type: ignore[union-attr]
    assert caplog.text.count("weather update failed") == 1
    assert await widget.refresh()
    assert "weather updates working again" in caplog.text


def test_refresh_interval() -> None:
    assert WeatherWidget(*NASHUA).refresh_seconds == 900
    assert WeatherWidget(*NASHUA, refresh_seconds=120).refresh_seconds == 120


async def test_fetch_json_reports_network_errors() -> None:
    with pytest.raises(OSError):  # urllib's URLError is an OSError
        await fetch_json("http://127.0.0.1:9/never", timeout=0.5)


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (0, "0:00"),
        (59.9, "0:59"),
        (61, "1:01"),
        (25 * 60, "25:00"),
        (3599, "59:59"),
        (3600, "1:00:00"),
        (3723, "1:02:03"),
        (-5, "0:00"),
    ],
)
def test_format_duration(seconds: float, text: str) -> None:
    assert format_duration(seconds) == text


def test_timer_counts_while_running() -> None:
    now = [10.0]
    timer = TimerWidget(clock=lambda: now[0])
    assert timer.face() == TimerFace()
    assert timer.press() and timer.running
    now[0] = 10.4
    assert timer.face() == TimerFace("0:00", pulse=True)
    now[0] = 11.2
    assert timer.face() == TimerFace("0:01", pulse=False)
    now[0] = 10 + 3723
    assert timer.face().elapsed == "1:02:03"  # type: ignore[union-attr]
    assert timer.press() and not timer.running
    assert timer.face() == TimerFace()
    timer.advance()  # no-op


def test_pomodoro_cycles_work_and_rest_and_notifies_on_change() -> None:
    now = [0.0]
    notes: list[tuple[str, str]] = []
    pomodoro = PomodoroWidget(
        25 * 60, 5 * 60, clock=lambda: now[0], notify=lambda t, b: notes.append((t, b))
    )
    assert pomodoro.face() == PomodoroFace()
    pomodoro.advance()  # stopped: nothing happens
    assert pomodoro.press() and pomodoro.running
    assert pomodoro.face() == PomodoroFace("work", "25:00", 0.0)
    now[0] = 10 * 60
    assert pomodoro.face() == PomodoroFace("work", "15:00", 0.4)
    pomodoro.advance()
    assert notes == []
    now[0] = 25 * 60 + 30
    assert pomodoro.face() == PomodoroFace("rest", "4:30", 0.1)
    pomodoro.advance()
    pomodoro.advance()  # notified once per change
    assert notes == [("Pomodoro: rest", "Take a 5:00 break")]
    now[0] = 30 * 60 + 1  # next cycle
    assert pomodoro.face().phase == "work"  # type: ignore[union-attr]
    pomodoro.advance()
    assert notes[-1] == ("Pomodoro: work", "Focus for 25:00")
    assert pomodoro.press() and not pomodoro.running
    assert pomodoro.face() == PomodoroFace()


def test_pomodoro_without_notifications_and_validation() -> None:
    now = [0.0]
    pomodoro = PomodoroWidget(60, 60, clock=lambda: now[0])
    pomodoro.press()
    now[0] = 61
    pomodoro.advance()  # no notifier: just tracks the phase
    with pytest.raises(ValueError):
        PomodoroWidget(0, 5)


def test_passive_widgets_let_presses_fall_through() -> None:
    assert not ClockWidget().press()
    assert not WeatherWidget(*NASHUA).press()
    ClockWidget().advance()


def test_desktop_notify_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def popen(argv: list[str], **kwargs: object) -> None:
        calls.append(argv)

    monkeypatch.setattr("linux.widgets.subprocess.Popen", popen)
    desktop_notify("Pomodoro: rest", "Take a 5:00 break")
    expected = ["notify-send", "--app-name=herdr-dock", "Pomodoro: rest", "Take a 5:00 break"]
    assert calls == [expected]

    def missing(argv: list[str], **kwargs: object) -> None:
        raise FileNotFoundError("notify-send")

    monkeypatch.setattr("linux.widgets.subprocess.Popen", missing)
    desktop_notify("x", "y")
