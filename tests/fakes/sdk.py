"""Fake vendor SDK for the M18 adapter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeSdkDevice:
    info: dict[str, Any]
    open_result: bool = True
    image_result: int = 0
    calls: list[tuple[Any, ...]] = field(default_factory=list)
    images: dict[int, bytes] = field(default_factory=dict)
    callback: Callable[[Any, Any], None] | None = None
    fail_close: bool = False
    fail_init: bool = False

    def open(self) -> bool:
        self.calls.append(("open",))
        return self.open_result

    def init(self) -> None:
        self.calls.append(("init",))
        if self.fail_init:
            raise OSError("init failed")

    def set_brightness(self, percent: int) -> None:
        self.calls.append(("brightness", percent))

    def set_key_image(self, key: int, path: str) -> int:
        self.calls.append(("image", key))
        with open(path, "rb") as file:
            self.images[key] = file.read()
        return self.image_result

    def refresh(self) -> None:
        self.calls.append(("refresh",))

    def clearAllIcon(self) -> None:
        self.calls.append(("clear",))

    def close(self, notify: bool = True) -> None:
        self.calls.append(("close",) if notify else ("close-removed",))
        if self.fail_close:
            raise OSError("already gone")

    def set_raw_read_callback(self, callback: Callable[[Any, Any], None]) -> None:
        self.callback = callback

    def press(self, code: int, state: int = 1) -> None:
        packet = b"ACK\x00\x00OK\x00\x00" + bytes([code, state]) + b"\x00" * 5
        assert self.callback is not None
        self.callback(self, packet)


@dataclass
class FakeSdk:
    devices: dict[tuple[int, int], list[dict[str, Any]]] = field(default_factory=dict)
    created: list[FakeSdkDevice] = field(default_factory=list)
    open_result: bool = True
    fail_init: bool = False

    def plug(self, vid: int, pid: int, path: str = "/dev/hidraw7") -> None:
        self.devices.setdefault((vid, pid), []).append({"path": path})

    def unplug(self) -> None:
        self.devices.clear()

    def enumerate(self, vendor_id: int, product_id: int) -> list[dict[str, Any]]:
        return list(self.devices.get((vendor_id, product_id), []))

    def create(self, info: dict[str, Any]) -> FakeSdkDevice:
        device = FakeSdkDevice(info, open_result=self.open_result, fail_init=self.fail_init)
        self.created.append(device)
        return device
