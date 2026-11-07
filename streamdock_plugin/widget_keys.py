"""Widget keys for the plugins: clock, weather, pomodoro, timer and app launcher actions.

Each is its own action (`<prefix><kind>`, e.g. `com.herdr.dock.clock`) that can sit on any key; its
settings come from the key's Property Inspector. The widgets are the Linux daemon's
(`linux/widgets.py`, standard library + `herdr_core` only). Unlike agent keys they don't depend on
the key's position, the grid or herdr: each context simply draws its own widget.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from herdr_core.config import ConfigError
from herdr_core.faces import Face, LauncherFace, WeatherFace
from linux.config import load_linux_config
from linux.hyprland import WindowFocuser
from linux.launcher import ShellLauncher
from linux.widgets import (
    ClockWidget,
    FetchJson,
    Notify,
    PomodoroWidget,
    TimerWidget,
    WeatherWidget,
    Widget,
    desktop_notify,
    fetch_json,
)
from streamdock_plugin.protocol import set_image_message

log = logging.getLogger(__name__)

WIDGET_KINDS = ("clock", "weather", "pomodoro", "timer", "app")
TICK_SECONDS = 1.0


def mac_notify(title: str, body: str) -> None:
    """Best-effort macOS notification (osascript); never raises."""

    def quoted(text: str) -> str:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

    script = f"display notification {quoted(body)} with title {quoted(title)}"
    try:
        subprocess.Popen(
            ["osascript", "-e", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        log.info("osascript unavailable: %s", exc)


def plugin_notify(platform: str = sys.platform) -> Notify:
    return mac_notify if platform == "darwin" else desktop_notify


def weather_defaults(path: Path) -> WeatherDefaults | None:
    """The first weather key of the M18 home page (`[[home]]` in config.toml), if any."""
    try:
        home = load_linux_config(path).home
    except ConfigError as exc:
        log.warning("no weather defaults: %s", exc)
        return None
    for key in home:
        if key.widget == "weather" and key.latitude is not None and key.longitude is not None:
            return WeatherDefaults(key.latitude, key.longitude, key.units, key.place)
    return None


def platform_apps(
    platform: str = sys.platform,
) -> tuple[Callable[[str], None], Callable[[str], Awaitable[bool]] | None]:
    """How app keys run a command, and focus a window first where we can (Hyprland on Linux)."""
    focus = WindowFocuser().focus_matching if platform.startswith("linux") else None
    return ShellLauncher().run, focus


@dataclass(frozen=True, slots=True)
class WeatherDefaults:
    """Where a weather key looks when its own settings have no location (from the config)."""

    latitude: float
    longitude: float
    units: str = "celsius"
    place: str = ""


class _AppWidget:
    """An app key's face; the press itself is handled by WidgetKeys (focus, else run)."""

    def __init__(self, label: str, symbol: str) -> None:
        self._face = LauncherFace(label, symbol)

    def face(self) -> Face:
        return self._face

    def press(self) -> bool:
        return False

    def advance(self) -> None:
        return None


class _NoLocation:
    """A weather key with no location in its settings or the config."""

    def face(self) -> Face:
        return WeatherFace("--", place="set location")

    def press(self) -> bool:
        return False

    def advance(self) -> None:
        return None


def _text(settings: Mapping[str, Any], key: str, default: str = "") -> str:
    value = settings.get(key)
    return value.strip() if isinstance(value, str) else default


def _number(settings: Mapping[str, Any], key: str) -> float | None:
    value = settings.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _positive(settings: Mapping[str, Any], key: str, default: float) -> float:
    value = _number(settings, key)
    return value if value is not None and value > 0 else default


def _flag(settings: Mapping[str, Any], key: str, default: bool) -> bool:
    value = settings.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip():
        return value.strip().lower() in ("1", "true", "yes", "on")
    return default


class WidgetBuilder:
    """Builds a widget from an action kind and the key's settings; bad values give defaults."""

    def __init__(
        self,
        *,
        weather: WeatherDefaults | None = None,
        clock: Callable[[], float] = time.monotonic,
        notify: Notify | None = None,
        fetch: FetchJson = fetch_json,
    ) -> None:
        self._weather = weather
        self._clock = clock
        self._notify = notify
        self._fetch = fetch

    def build(self, kind: str, settings: Mapping[str, Any]) -> Widget | None:
        if kind == "clock":
            if _flag(settings, "hour12", False):
                return ClockWidget("%-I:%M")
            return ClockWidget()
        if kind == "timer":
            return TimerWidget(clock=self._clock)
        if kind == "pomodoro":
            return PomodoroWidget(
                _positive(settings, "work", 25) * 60,
                _positive(settings, "rest", 5) * 60,
                clock=self._clock,
                notify=self._notify if _flag(settings, "notify", True) else None,
            )
        if kind == "weather":
            return self._weather_widget(settings)
        if kind == "app":
            return _AppWidget(_text(settings, "label"), _text(settings, "symbol"))
        return None

    def _weather_widget(self, settings: Mapping[str, Any]) -> Widget:
        latitude, longitude = _number(settings, "latitude"), _number(settings, "longitude")
        defaults = self._weather
        if latitude is None or longitude is None:
            if defaults is None:
                return _NoLocation()
            latitude, longitude = defaults.latitude, defaults.longitude
        units = _text(settings, "units") or (defaults.units if defaults else "celsius")
        place = _text(settings, "place") or (defaults.place if defaults else "")
        return WeatherWidget(
            latitude,
            longitude,
            units="fahrenheit" if units == "fahrenheit" else "celsius",
            place=place,
            fetch=self._fetch,
        )


@dataclass(slots=True)
class _Key:
    kind: str
    settings: str
    """The settings as canonical JSON: the widget is rebuilt only when they change."""
    widget: Widget | None
    visible: bool = True
    shown: Face | None = None
    tasks: list[asyncio.Task[None]] = field(default_factory=list)


class WidgetKeys:
    """Draws and presses the widget keys, one widget per key context."""

    def __init__(
        self,
        prefix: str,
        send: Callable[[str], None],
        render: Callable[[Face], bytes],
        builder: WidgetBuilder,
        *,
        run: Callable[[str], None],
        focus: Callable[[str], Awaitable[bool]] | None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._kinds = {prefix + kind: kind for kind in WIDGET_KINDS}
        self._send = send
        self._render = render
        self._builder = builder
        self._run = run
        self._focus = focus
        self._sleep = sleep
        self._keys: dict[str, _Key] = {}

    def handles(self, action: str) -> bool:
        return action in self._kinds

    def appeared(self, context: str, action: str, settings: Mapping[str, Any]) -> None:
        """A widget key became visible, moved, or got new settings."""
        key = self._key(context, action, settings)
        key.visible = True
        key.shown = None  # never drawn on this appearance
        self._draw(context, key)

    def disappeared(self, context: str) -> None:
        """Hidden, not forgotten: a running pomodoro keeps going and notifies."""
        key = self._keys.get(context)
        if key is not None:
            key.visible = False

    async def pressed(self, context: str, action: str, settings: Mapping[str, Any]) -> None:
        key = self._keys.get(context)
        if key is None or key.widget is None:
            return
        if key.widget.press():
            self._draw(context, key)
            return
        if key.kind == "app":
            await self._open_app(settings)

    def tick(self) -> None:
        """Advance every widget, then redraw the visible keys whose face changed."""
        for context, key in self._keys.items():
            if key.widget is None:
                continue
            try:
                key.widget.advance()
            except Exception:
                log.warning("advancing the %s key failed", key.kind, exc_info=True)
            if key.visible:
                self._draw(context, key)

    async def run(self) -> None:
        while True:
            await self._sleep(TICK_SECONDS)
            self.tick()

    async def close(self) -> None:
        tasks = [task for key in self._keys.values() for task in key.tasks]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _key(self, context: str, action: str, settings: Mapping[str, Any]) -> _Key:
        kind = self._kinds[action]
        canonical = json.dumps(dict(settings), sort_keys=True, default=str)
        key = self._keys.get(context)
        if key is not None and key.kind == kind and key.settings == canonical:
            return key
        if key is not None:
            for task in key.tasks:
                task.cancel()
        widget = self._builder.build(kind, settings)
        key = _Key(kind, canonical, widget)
        if isinstance(widget, WeatherWidget):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:  # no loop (only in tests): the key shows "--"
                loop = None
            if loop is not None:
                key.tasks.append(
                    loop.create_task(self._refresh_weather(context, key, widget), name="weather")
                )
        self._keys[context] = key
        log.info("%s key appeared", kind)
        return key

    def _draw(self, context: str, key: _Key) -> None:
        if key.widget is None:
            return
        try:
            face = key.widget.face()
        except Exception:
            log.warning("drawing the %s key failed", key.kind, exc_info=True)
            return
        if face == key.shown:
            return
        self._send(set_image_message(context, self._render(face)))
        key.shown = face

    async def _refresh_weather(self, context: str, key: _Key, widget: WeatherWidget) -> None:
        """Never raises: a failed fetch keeps the last reading and retries sooner."""
        while True:
            ok = await widget.refresh()
            if ok and key.visible:
                self._draw(context, key)
            await self._sleep(widget.refresh_seconds if ok else widget.RETRY_SECONDS)

    async def _open_app(self, settings: Mapping[str, Any]) -> None:
        pattern, command = _text(settings, "focus"), _text(settings, "command")
        if pattern and self._focus is not None:
            try:
                if await self._focus(pattern):
                    return
            except Exception:
                log.warning("focusing a %r window failed", pattern, exc_info=True)
        if command:
            self._run(command)
        else:
            log.info("app key has no command to run")
