"""herdr-dock configuration (TOML)."""

from __future__ import annotations

import logging
import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from herdr_core.animation import AnimationConfig
from herdr_core.models import AgentStatus, LabelStyle

log = logging.getLogger(__name__)

_LABEL_STYLES: tuple[LabelStyle, ...] = ("cwd", "title", "name")
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


HERDR_WINDOW = "herdr-window"
"""`[raise]` value meaning: bring forward the terminal the herdr client runs in."""


class ConfigError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RaiseConfig:
    enabled: bool = True
    linux: str = ""
    macos: str = ""


@dataclass(frozen=True, slots=True)
class Config:
    herdr_socket: str = ""
    herdr_bin: str = ""
    """Path to the herdr binary; empty = find it automatically."""
    label: LabelStyle = "cwd"
    resync_seconds: float = 30.0
    raise_window: RaiseConfig = field(default_factory=RaiseConfig)
    animation: AnimationConfig = field(default_factory=AnimationConfig)
    colors: Mapping[AgentStatus, str] = field(default_factory=dict)
    """Status colour overrides (#rrggbb)."""


def default_config_path(env: Mapping[str, str], home: Path) -> Path:
    base = Path(env["XDG_CONFIG_HOME"]) if env.get("XDG_CONFIG_HOME") else home / ".config"
    return base / "herdr-dock" / "config.toml"


def load_config(path: Path | None = None) -> Config:
    """Load the config file; a missing default file means all defaults."""
    explicit = path is not None
    path = path or default_config_path(os.environ, Path.home())
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if explicit:
            raise ConfigError(f"config file not found: {path}") from None
        return Config()
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    return parse_config(data)


def parse_config(data: Mapping[str, Any]) -> Config:
    known = {
        "herdr_socket",
        "herdr_bin",
        "label",
        "resync_seconds",
        "raise",
        "animate",
        "blink_hz",
        "spinner_fps",
        "pulse_hz",
        "attention",
        "colors",
    }
    for key in sorted(set(data) - known):
        log.debug("ignoring config key %r (not used by herdr_core)", key)

    label = data.get("label", "cwd")
    if label not in _LABEL_STYLES:
        raise ConfigError(f"label must be one of {', '.join(_LABEL_STYLES)}, got {label!r}")
    resync = _positive(data, "resync_seconds", 30.0)

    return Config(
        herdr_socket=_string(data, "herdr_socket"),
        herdr_bin=_string(data, "herdr_bin"),
        label=cast(LabelStyle, label),
        resync_seconds=resync,
        raise_window=_parse_raise(data.get("raise", {})),
        animation=_parse_animation(data),
        colors=_parse_colors(data.get("colors", {})),
    )


def _parse_animation(data: Mapping[str, Any]) -> AnimationConfig:
    enabled = data.get("animate", True)
    if not isinstance(enabled, bool):
        raise ConfigError(f"animate must be true or false, got {enabled!r}")
    rates: dict[str, float] = {}
    for key, default in (("blink_hz", 2.0), ("spinner_fps", 4.0), ("pulse_hz", 0.7)):
        rates[key] = _positive(data, key, default)
    attention = data.get("attention", ["blocked"])
    if not isinstance(attention, list):
        raise ConfigError(f"attention must be a list of statuses, got {attention!r}")
    return AnimationConfig(
        enabled=enabled,
        blink_hz=rates["blink_hz"],
        spinner_fps=rates["spinner_fps"],
        pulse_hz=rates["pulse_hz"],
        attention=frozenset(_status(name, "attention") for name in attention),
    )


def _parse_colors(raw: object) -> dict[AgentStatus, str]:
    if not isinstance(raw, Mapping):
        raise ConfigError("[colors] must be a table")
    colors: dict[AgentStatus, str] = {}
    for name, value in raw.items():
        if not isinstance(value, str) or not _HEX_COLOR.match(value):
            raise ConfigError(f"colors.{name} must be #rrggbb, got {value!r}")
        colors[_status(name, "colors")] = value
    return colors


def _status(name: object, where: str) -> AgentStatus:
    try:
        return AgentStatus(str(name))
    except ValueError:
        valid = ", ".join(status.value for status in AgentStatus)
        raise ConfigError(f"{where}: unknown status {name!r} (use {valid})") from None


def _positive(data: Mapping[str, Any], key: str, default: float) -> float:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ConfigError(f"{key} must be a positive number, got {value!r}")
    return float(value)


def _parse_raise(raw: object) -> RaiseConfig:
    if not isinstance(raw, Mapping):
        raise ConfigError("[raise] must be a table")
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ConfigError(f"raise.enabled must be true or false, got {enabled!r}")
    return RaiseConfig(
        enabled=enabled,
        linux=_string(raw, "linux", "raise."),
        macos=_string(raw, "macos", "raise."),
    )


def _string(data: Mapping[str, Any], key: str, prefix: str = "") -> str:
    value = data.get(key, "")
    if not isinstance(value, str):
        raise ConfigError(f"{prefix}{key} must be a string, got {value!r}")
    return value
