"""Elgato front-end settings (`[elgato]`), read from the same TOML file as herdr_core's config."""

from __future__ import annotations

import json
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from herdr_core.config import ConfigError, default_config_path

DEFAULT_SIZE = (5, 3)
"""Used when neither the config nor the app's launch info names a dock."""
MIN_KEYS = 2
"""One agent key and a pager is the least the core can lay out."""
MIN_KEY_SIZE = 16
DEFAULT_KEY_SIZE = 144
DEFAULT_CORNER_RADIUS = 0.15


@dataclass(frozen=True, slots=True)
class ElgatoConfig:
    columns: int = 0
    rows: int = 0
    """Dock size. 0 = take the first device in the app's launch info."""
    key_size: int = DEFAULT_KEY_SIZE
    """Pixels per key image (the app shows 72 px keys at 1x and 144 px at 2x)."""
    corner_radius: float = DEFAULT_CORNER_RADIUS
    """Key corner radius as a fraction of the key size: the app draws rounded keys. 0 = square."""
    portrait: bool = False
    """Number the keys as a phone held upright shows them (the dock turned clockwise)."""
    mirror: bool = False
    """The display shows each row right to left (the first key is on the right)."""
    folder: bool = True
    """The keys are in a folder: the app's back key takes the top-left key, so it is reserved."""


def load_elgato_config(path: Path | None = None, *, explicit: bool = True) -> ElgatoConfig:
    """Read `[elgato]`; a missing default file (explicit=False) means all defaults."""
    if path is None:
        path, explicit = default_config_path(os.environ, Path.home()), False
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if explicit:
            raise ConfigError(f"config file not found: {path}") from None
        return ElgatoConfig()
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    return _parse(data.get("elgato", {}))


def devices_from_info(info: str) -> list[tuple[int, int]]:
    """(columns, rows) of every device in the app's `-info` JSON, in the app's order."""
    try:
        data = json.loads(info)
    except ValueError:
        return []
    devices = data.get("devices") if isinstance(data, dict) else None
    if not isinstance(devices, list):
        return []
    sizes: list[tuple[int, int]] = []
    for device in devices:
        size = device.get("size") if isinstance(device, dict) else None
        columns = _int(size.get("columns")) if isinstance(size, dict) else None
        rows = _int(size.get("rows")) if isinstance(size, dict) else None
        if columns is not None and rows is not None:
            sizes.append((columns, rows))
    return sizes


def choose_size(config: ElgatoConfig, devices: list[tuple[int, int]]) -> tuple[int, int]:
    """The dock size to serve: config first, then the first usable launch-info device."""
    if config.columns and config.rows:
        return config.columns, config.rows
    for columns, rows in devices:
        if columns > 0 and rows > 0 and columns * rows >= MIN_KEYS:
            return columns, rows
    return DEFAULT_SIZE


def _parse(raw: object) -> ElgatoConfig:
    if not isinstance(raw, Mapping):
        raise ConfigError("[elgato] must be a table")
    columns, rows = _count(raw, "columns"), _count(raw, "rows")
    if bool(columns) != bool(rows):
        raise ConfigError("elgato.columns and elgato.rows go together: set both or neither")
    if columns * rows and columns * rows < MIN_KEYS:
        raise ConfigError(f"elgato: a {columns}x{rows} dock is too small (need at least 2 keys)")
    key_size = _int(raw.get("key_size", DEFAULT_KEY_SIZE))
    if key_size is None or key_size < MIN_KEY_SIZE:
        raise ConfigError(f"elgato.key_size must be a whole number >= {MIN_KEY_SIZE}")
    return ElgatoConfig(
        columns=columns,
        rows=rows,
        key_size=key_size,
        corner_radius=_radius(raw),
        portrait=_flag(raw, "portrait", False),
        mirror=_flag(raw, "mirror", False),
        folder=_flag(raw, "folder", True),
    )


def _radius(data: Mapping[str, Any]) -> float:
    value = data.get("corner_radius", DEFAULT_CORNER_RADIUS)
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 0.5:
        raise ConfigError(f"elgato.corner_radius must be between 0 and 0.5, got {value!r}")
    return float(value)


def _flag(data: Mapping[str, Any], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"elgato.{key} must be true or false, got {value!r}")
    return value


def _count(data: Mapping[str, Any], key: str) -> int:
    value = data.get(key, 0)
    number = _int(value)
    if number is None or number < 0:
        raise ConfigError(f"elgato.{key} must be a whole number, got {value!r}")
    return number


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
