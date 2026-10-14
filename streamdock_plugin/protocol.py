"""The StreamDock app's plugin protocol: JSON messages over a local WebSocket.

Pure functions only. Incoming messages become small immutable events, and anything we don't
use (or can't parse) becomes None, so a surprising message can never crash the plugin.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Appeared:
    """A key holding one of our actions became visible, or moved (new coordinates)."""

    context: str
    device: str
    action: str
    column: int
    row: int


@dataclass(frozen=True, slots=True)
class Disappeared:
    context: str


@dataclass(frozen=True, slots=True)
class KeyReleased:
    context: str
    device: str
    action: str
    column: int
    row: int


@dataclass(frozen=True, slots=True)
class DeviceConnected:
    device: str
    name: str
    columns: int
    rows: int


@dataclass(frozen=True, slots=True)
class DeviceDisconnected:
    device: str


PluginEvent = Appeared | Disappeared | KeyReleased | DeviceConnected | DeviceDisconnected


def parse_event(raw: str) -> PluginEvent | None:
    """Decode one message from the app; None if it's unused or malformed."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    event = data.get("event")
    if event == "willDisappear":
        context = _text(data, "context")
        return Disappeared(context) if context else None
    if event in ("willAppear", "keyUp"):
        return _key_event(event, data)
    if event == "deviceDidConnect":
        return _device_connected(data)
    if event == "deviceDidDisconnect":
        device = _text(data, "device")
        return DeviceDisconnected(device) if device else None
    return None


def register_message(register_event: str, plugin_uuid: str) -> str:
    """First message after connecting: tells the app which plugin this is."""
    return json.dumps({"event": register_event, "uuid": plugin_uuid})


def set_image_message(context: str, png: bytes) -> str:
    image = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    return json.dumps(
        {"event": "setImage", "context": context, "payload": {"target": 0, "image": image}}
    )


def _key_event(event: str, data: dict[str, Any]) -> Appeared | KeyReleased | None:
    context, device = _text(data, "context"), _text(data, "device")
    payload = data.get("payload")
    coordinates = payload.get("coordinates") if isinstance(payload, dict) else None
    if not context or not isinstance(coordinates, dict):
        return None  # no key position: a dial or something else we don't draw on
    column, row = _int(coordinates, "column"), _int(coordinates, "row")
    if column is None or row is None:
        return None
    action = _text(data, "action")
    if event == "willAppear":
        return Appeared(context, device, action, column, row)
    return KeyReleased(context, device, action, column, row)


def _device_connected(data: dict[str, Any]) -> DeviceConnected | None:
    device = _text(data, "device")
    info = data.get("deviceInfo")
    size = info.get("size") if isinstance(info, dict) else None
    if not device or not isinstance(info, dict) or not isinstance(size, dict):
        return None
    columns, rows = _int(size, "columns"), _int(size, "rows")
    if columns is None or rows is None:
        return None
    return DeviceConnected(device, _text(info, "name"), columns, rows)


def _text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    return value if isinstance(value, str) else ""


def _int(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None
