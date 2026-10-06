from __future__ import annotations

import base64
import json

from macos.protocol import (
    Appeared,
    DeviceConnected,
    DeviceDisconnected,
    Disappeared,
    KeyReleased,
    parse_event,
    register_message,
    set_image_message,
)

ACTION = "com.herdr.dock.agent"


def raw(event: str, **fields: object) -> str:
    return json.dumps({"event": event, **fields})


def key_payload(column: int, row: int) -> dict[str, object]:
    return {"controller": "Keypad", "coordinates": {"column": column, "row": row}, "settings": {}}


def test_will_appear_carries_context_device_and_coordinates() -> None:
    message = raw("willAppear", action=ACTION, context="c1", device="d1", payload=key_payload(2, 1))
    assert parse_event(message) == Appeared("c1", "d1", ACTION, column=2, row=1)


def test_will_disappear() -> None:
    message = raw(
        "willDisappear", action=ACTION, context="c1", device="d1", payload=key_payload(0, 0)
    )
    assert parse_event(message) == Disappeared("c1")


def test_key_up_is_a_release_and_key_down_is_ignored() -> None:
    up = raw("keyUp", action=ACTION, context="c1", device="d1", payload=key_payload(1, 2))
    assert parse_event(up) == KeyReleased("c1", "d1", ACTION, column=1, row=2)
    assert (
        parse_event(raw("keyDown", action=ACTION, context="c1", payload=key_payload(1, 2))) is None
    )


def test_device_events() -> None:
    connected = raw(
        "deviceDidConnect",
        device="d1",
        deviceInfo={"name": "VSDM18", "size": {"columns": 5, "rows": 3}, "type": 0},
    )
    assert parse_event(connected) == DeviceConnected("d1", "VSDM18", columns=5, rows=3)
    assert parse_event(raw("deviceDidDisconnect", device="d1")) == DeviceDisconnected("d1")


def test_unknown_events_are_ignored() -> None:
    assert parse_event(raw("titleParametersDidChange", context="c1", payload={})) is None


def test_malformed_input_never_raises() -> None:
    for bad in (
        "not json",
        "[]",
        "42",
        raw("willAppear"),  # no context
        raw("willAppear", context="c1", payload={"coordinates": {"column": "x", "row": 1}}),
        raw("willAppear", context="c1", payload={"coordinates": None}),
        raw("willAppear", context="c1", payload="oops"),
        raw("deviceDidConnect", device="d1", deviceInfo={"size": {}}),
        raw("deviceDidConnect", device="d1", deviceInfo=None),
    ):
        assert parse_event(bad) is None, bad


def test_will_appear_without_coordinates_is_ignored() -> None:
    """Dials and other controllers have no key position."""
    assert parse_event(raw("willAppear", context="c1", device="d1", payload={})) is None


def test_register_message() -> None:
    assert json.loads(register_message("registerPlugin", "UUID1")) == {
        "event": "registerPlugin",
        "uuid": "UUID1",
    }


def test_set_image_message_is_a_png_data_url() -> None:
    message = json.loads(set_image_message("c1", b"\x89PNGdata"))
    assert message["event"] == "setImage"
    assert message["context"] == "c1"
    assert message["payload"]["target"] == 0
    url = message["payload"]["image"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == b"\x89PNGdata"
