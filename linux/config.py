"""Linux front-end settings, read from the same TOML file as herdr_core's config."""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from herdr_core.config import ConfigError, default_config_path

KEY_COUNT = 15
BUTTON_NAMES = ("left", "middle", "right")
BUTTON_ACTIONS = ("herdr", "page", "none")
WIDGETS = ("clock", "weather")
UNITS = ("celsius", "fahrenheit")
DEFAULT_DEVICE_IDS: tuple[tuple[int, int], ...] = (
    (0x5548, 0x1000),
    (0x6603, 0x1009),
    (0x6603, 0x1012),
)
HERDR_WINDOW = "herdr-window"
"""`[raise] linux` value meaning: focus the window the herdr client runs in (Hyprland)."""


@dataclass(frozen=True, slots=True)
class HomeKey:
    key: int
    """1-based physical key, left to right, top to bottom."""
    label: str
    run: str = ""
    app: str = ""
    herdr: bool = False
    icon: str = ""
    symbol: str = ""
    focus: str = ""
    """Window class regex: focus a matching window if one exists, else run/app."""
    widget: str = ""
    """"clock" or "weather": a live key (pressing it still runs run/app/focus, if set)."""
    time_format: str = "%H:%M"
    date_format: str = "%a\n%-d %b"
    latitude: float | None = None
    longitude: float | None = None
    units: str = "celsius"
    place: str = ""
    refresh_minutes: float = 15.0
    """How often the weather key fetches new conditions."""

    @property
    def index(self) -> int:
        return self.key - 1


DEFAULT_HOME: tuple[HomeKey, ...] = (HomeKey(key=1, label="herdr", herdr=True, symbol="◐"),)


@dataclass(frozen=True, slots=True)
class LinuxConfig:
    brightness: int = 70
    device_ids: tuple[tuple[int, int], ...] = DEFAULT_DEVICE_IDS
    app_launcher: str = "uwsm-app -- {app}"
    home: tuple[HomeKey, ...] = DEFAULT_HOME
    buttons: Mapping[str, str] = field(
        default_factory=lambda: {"left": "herdr", "middle": "none", "right": "page"}
    )
    poll_seconds: float = 2.0
    focus_herdr_on_enter: bool = True
    """Entering Herdr mode also brings the herdr window to the front."""
    blank_when_locked: bool = True
    """Turn the dock off while the session is locked (Hyprland session lock)."""
    blank_on_sleep: bool = True
    """Turn the dock off when the machine suspends (logind PrepareForSleep)."""
    lock_poll_seconds: float = 1.0


def load_linux_config(path: Path | None = None) -> LinuxConfig:
    path = path or default_config_path(os.environ, Path.home())
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return LinuxConfig()
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    return parse_linux_config(data, base_dir=path.absolute().parent)


def parse_linux_config(data: Mapping[str, Any], base_dir: Path | None = None) -> LinuxConfig:
    """`base_dir`: where relative icon paths are resolved (the config file's folder)."""
    raw = data.get("linux", {})
    if not isinstance(raw, Mapping):
        raise ConfigError("[linux] must be a table")
    defaults = LinuxConfig()
    brightness = raw.get("brightness", defaults.brightness)
    if (
        isinstance(brightness, bool)
        or not isinstance(brightness, int)
        or not 0 <= brightness <= 100
    ):
        raise ConfigError(f"linux.brightness must be 0-100, got {brightness!r}")
    poll = raw.get("poll_seconds", defaults.poll_seconds)
    if isinstance(poll, bool) or not isinstance(poll, int | float) or poll <= 0:
        raise ConfigError(f"linux.poll_seconds must be a positive number, got {poll!r}")
    flags = {
        name: _bool(raw, name, getattr(defaults, name))
        for name in ("focus_herdr_on_enter", "blank_when_locked", "blank_on_sleep")
    }
    lock_poll = raw.get("lock_poll_seconds", defaults.lock_poll_seconds)
    if isinstance(lock_poll, bool) or not isinstance(lock_poll, int | float) or lock_poll <= 0:
        raise ConfigError(f"linux.lock_poll_seconds must be a positive number, got {lock_poll!r}")
    launcher = raw.get("app_launcher", defaults.app_launcher)
    if not isinstance(launcher, str) or "{app}" not in launcher:
        raise ConfigError("linux.app_launcher must be a string containing {app}")
    return LinuxConfig(
        brightness=brightness,
        device_ids=_device_ids(raw.get("device_ids")) or defaults.device_ids,
        app_launcher=launcher,
        home=_home(data.get("home"), base_dir or Path.cwd()) or defaults.home,
        buttons=_buttons(raw.get("buttons", {}), defaults.buttons),
        poll_seconds=float(poll),
        lock_poll_seconds=float(lock_poll),
        **flags,
    )


def _bool(raw: Mapping[str, Any], name: str, default: bool) -> bool:
    value = raw.get(name, default)
    if not isinstance(value, bool):
        raise ConfigError(f"linux.{name} must be true or false, got {value!r}")
    return value


def _device_ids(raw: object) -> tuple[tuple[int, int], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError('linux.device_ids must be a list like ["5548:1000"]')
    ids = []
    for entry in raw:
        vid, sep, pid = str(entry).partition(":")
        try:
            ids.append((int(vid, 16), int(pid, 16)))
        except ValueError:
            raise ConfigError(f"linux.device_ids: expected VID:PID in hex, got {entry!r}") from None
        if not sep:
            raise ConfigError(f"linux.device_ids: expected VID:PID in hex, got {entry!r}")
    return tuple(ids)


def _buttons(raw: object, defaults: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        raise ConfigError("[linux.buttons] must be a table")
    buttons = dict(defaults)
    for name, action in raw.items():
        if name not in BUTTON_NAMES:
            raise ConfigError(
                f"linux.buttons: unknown button {name!r} (use {', '.join(BUTTON_NAMES)})"
            )
        if action not in BUTTON_ACTIONS:
            raise ConfigError(
                f"linux.buttons.{name}: unknown action {action!r} (use {', '.join(BUTTON_ACTIONS)})"
            )
        buttons[name] = action
    return buttons


def _home(raw: object, base_dir: Path) -> tuple[HomeKey, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError("home must be an array of tables ([[home]])")
    keys: list[HomeKey] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            raise ConfigError("each [[home]] entry must be a table")
        key = entry.get("key")
        if isinstance(key, bool) or not isinstance(key, int) or not 1 <= key <= KEY_COUNT:
            raise ConfigError(f"home.key must be 1-{KEY_COUNT}, got {key!r}")
        if any(existing.key == key for existing in keys):
            raise ConfigError(f"home.key {key} is used twice")
        home_key = HomeKey(
            key=key,
            label=_text(entry, "label", key),
            run=_text(entry, "run", key),
            app=_text(entry, "app", key),
            herdr=_flag(entry, "herdr", key),
            icon=_path(_text(entry, "icon", key), base_dir),
            symbol=_text(entry, "symbol", key),
            focus=_text(entry, "focus", key),
            **_widget(entry, key),
        )
        launches = sum(1 for action in (home_key.run, home_key.app) if action)
        if home_key.herdr and (launches or home_key.focus or home_key.widget):
            raise ConfigError(f"home key {key}: herdr = true can't be combined with other actions")
        if launches > 1 or not (launches or home_key.herdr or home_key.focus or home_key.widget):
            raise ConfigError(
                f"home key {key}: set exactly one of run, app, herdr = true or widget "
                "(focus and widget can be combined with run/app)"
            )
        if home_key.focus:
            try:
                re.compile(home_key.focus)
            except re.error as exc:
                raise ConfigError(f"home key {key}: invalid focus pattern: {exc}") from None
        keys.append(home_key)
    return tuple(keys)


def _widget(entry: Mapping[str, Any], key: int) -> dict[str, Any]:
    widget = _text(entry, "widget", key)
    if not widget:
        return {}
    if widget not in WIDGETS:
        raise ConfigError(f"home key {key}: widget must be one of {', '.join(WIDGETS)}")
    if widget == "clock":
        return {
            "widget": widget,
            "time_format": _text(entry, "time_format", key) or "%H:%M",
            "date_format": str(entry.get("date_format", "%a\n%-d %b")),
        }
    units = entry.get("units", "celsius")
    if units not in UNITS:
        raise ConfigError(f"home key {key}: units must be one of {', '.join(UNITS)}")
    return {
        "widget": widget,
        "latitude": _coordinate(entry, "latitude", key, 90),
        "longitude": _coordinate(entry, "longitude", key, 180),
        "units": units,
        "place": _text(entry, "place", key),
        "refresh_minutes": _refresh_minutes(entry, key),
    }


def _refresh_minutes(entry: Mapping[str, Any], key: int) -> float:
    value = entry.get("refresh_minutes", 15)
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 1:
        raise ConfigError(f"home key {key}: refresh_minutes must be a number >= 1, got {value!r}")
    return float(value)


def _coordinate(entry: Mapping[str, Any], name: str, key: int, limit: int) -> float:
    value = entry.get(name)
    if isinstance(value, bool) or not isinstance(value, int | float) or abs(value) > limit:
        raise ConfigError(
            f"home key {key}: weather needs {name} as a number between -{limit} and {limit}"
        )
    return float(value)


def _path(value: str, base_dir: Path) -> str:
    """Absolute path: the daemon changes its working directory for the SDK."""
    if not value:
        return ""
    return str((base_dir / Path(value).expanduser()).absolute())


def _text(entry: Mapping[str, Any], name: str, key: int) -> str:
    value = entry.get(name, "")
    if not isinstance(value, str):
        raise ConfigError(f"home key {key}: {name} must be a string")
    return value


def _flag(entry: Mapping[str, Any], name: str, key: int) -> bool:
    value = entry.get(name, False)
    if not isinstance(value, bool):
        raise ConfigError(f"home key {key}: {name} must be true or false")
    return value
