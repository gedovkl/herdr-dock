"""herdr-dock configuration (TOML)."""

from __future__ import annotations

import logging
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from herdr_core.models import LabelStyle

log = logging.getLogger(__name__)

_LABEL_STYLES: tuple[LabelStyle, ...] = ("cwd", "title", "name")


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
    label: LabelStyle = "cwd"
    resync_seconds: float = 30.0
    raise_window: RaiseConfig = field(default_factory=RaiseConfig)


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
    known = {"herdr_socket", "label", "resync_seconds", "raise"}
    for key in sorted(set(data) - known):
        log.debug("ignoring config key %r (not used by herdr_core)", key)

    label = data.get("label", "cwd")
    if label not in _LABEL_STYLES:
        raise ConfigError(f"label must be one of {', '.join(_LABEL_STYLES)}, got {label!r}")
    resync = data.get("resync_seconds", 30.0)
    if isinstance(resync, bool) or not isinstance(resync, int | float) or resync <= 0:
        raise ConfigError(f"resync_seconds must be a positive number, got {resync!r}")

    return Config(
        herdr_socket=_string(data, "herdr_socket"),
        label=cast(LabelStyle, label),
        resync_seconds=float(resync),
        raise_window=_parse_raise(data.get("raise", {})),
    )


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
