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


def load_linux_config(path: Path | None = None) -> LinuxConfig:
    path = path or default_config_path(os.environ, Path.home())
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return LinuxConfig()
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    return parse_linux_config(data)


def parse_linux_config(data: Mapping[str, Any]) -> LinuxConfig:
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
    launcher = raw.get("app_launcher", defaults.app_launcher)
    if not isinstance(launcher, str) or "{app}" not in launcher:
        raise ConfigError("linux.app_launcher must be a string containing {app}")
    return LinuxConfig(
        brightness=brightness,
        device_ids=_device_ids(raw.get("device_ids")) or defaults.device_ids,
        app_launcher=launcher,
        home=_home(data.get("home")) or defaults.home,
        buttons=_buttons(raw.get("buttons", {}), defaults.buttons),
        poll_seconds=float(poll),
    )


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


def _home(raw: object) -> tuple[HomeKey, ...]:
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
            icon=os.path.expanduser(_text(entry, "icon", key)),
            symbol=_text(entry, "symbol", key),
            focus=_text(entry, "focus", key),
        )
        launches = sum(1 for action in (home_key.run, home_key.app) if action)
        if home_key.herdr and (launches or home_key.focus):
            raise ConfigError(f"home key {key}: herdr = true can't be combined with other actions")
        if launches > 1 or not (launches or home_key.herdr or home_key.focus):
            raise ConfigError(
                f"home key {key}: set exactly one of run, app or herdr = true "
                "(optionally with focus)"
            )
        if home_key.focus:
            try:
                re.compile(home_key.focus)
            except re.error as exc:
                raise ConfigError(f"home key {key}: invalid focus pattern: {exc}") from None
        keys.append(home_key)
    return tuple(keys)


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
