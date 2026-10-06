from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from linux.device import (
    ButtonPressed,
    DeviceError,
    DeviceInput,
    DevicePermissionError,
    KeyPressed,
    M18Device,
    decode_packet,
)
from tests.fakes.sdk import FakeSdk


def packet(code: int, state: int = 1) -> bytes:
    return b"ACK\x00\x00OK\x00\x00" + bytes([code, state]) + b"\x00" * 5


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (packet(1), KeyPressed(0)),
        (packet(15), KeyPressed(14)),
        (packet(0x25), ButtonPressed("left")),
        (packet(0x30), ButtonPressed("middle")),
        (packet(0x31), ButtonPressed("right")),
        (packet(1, 0), None),  # release
        (packet(0x40), None),  # unknown code
        (packet(0), None),
        (b"ACK", None),
        (b"XYZ\x00\x00OK\x00\x00\x01\x01", None),
    ],
)
def test_decode_packet(data: bytes, expected: DeviceInput | None) -> None:
    assert decode_packet(data) == expected


@pytest.fixture
async def rig(tmp_path: Path) -> AsyncIterator[tuple[FakeSdk, M18Device, list[DeviceInput]]]:
    cwd = os.getcwd()
    sdk, inputs = FakeSdk(), []
    device = M18Device(
        sdk,
        [(0x5548, 0x1000)],
        tmp_path / "work",
        inputs.append,
        brightness=55,
        access=lambda path: True,
    )
    yield sdk, device, inputs
    await device.shutdown()
    os.chdir(cwd)


Rig = tuple[FakeSdk, M18Device, list[DeviceInput]]


async def test_connect_initialises_device(rig: Rig) -> None:
    sdk, device, _ = rig
    assert not await device.connect()
    sdk.plug(0x5548, 0x1000)
    assert await device.connect()
    assert await device.connect()  # already connected
    assert device.connected
    assert sdk.created[0].calls == [
        ("open",),
        ("init",),
        ("brightness", 55),
        ("clear",),
        ("refresh",),
    ]
    assert Path.cwd().name == "work"  # the SDK writes temp files into the cwd


async def test_show_maps_physical_index_to_sdk_key(
    rig: tuple[FakeSdk, M18Device, list[DeviceInput]],
) -> None:
    sdk, device, _ = rig
    sdk.plug(0x5548, 0x1000)
    await device.connect()
    await device.show(0, b"png-0")
    await device.show(14, b"png-14")
    assert sdk.created[0].images == {1: b"png-0", 15: b"png-14"}
    with pytest.raises(ValueError):
        await device.show(15, b"x")


async def test_presses_reach_the_loop(rig: tuple[FakeSdk, M18Device, list[DeviceInput]]) -> None:
    sdk, device, inputs = rig
    sdk.plug(0x5548, 0x1000)
    await device.connect()
    await asyncio.to_thread(sdk.created[0].press, 3)  # SDK reader thread
    await asyncio.to_thread(sdk.created[0].press, 3, 0)
    await asyncio.to_thread(sdk.created[0].press, 0x31)
    for _ in range(10):
        await asyncio.sleep(0)
    assert inputs == [KeyPressed(2), ButtonPressed("right")]


async def test_permission_check_before_open(tmp_path: Path) -> None:
    sdk = FakeSdk()
    sdk.plug(0x5548, 0x1000)
    device = M18Device(sdk, [(0x5548, 0x1000)], tmp_path, lambda e: None, access=lambda p: False)
    try:
        with pytest.raises(DevicePermissionError, match=r"install-linux\.sh --udev"):
            await device.connect()
        assert sdk.created == []
    finally:
        await device.shutdown()


async def test_open_failure(rig: tuple[FakeSdk, M18Device, list[DeviceInput]]) -> None:
    sdk, device, _ = rig
    sdk.plug(0x5548, 0x1000)
    sdk.open_result = False
    with pytest.raises(DeviceError, match="opening"):
        await device.connect()
    assert not device.connected


async def test_image_failure_and_not_connected(
    rig: tuple[FakeSdk, M18Device, list[DeviceInput]],
) -> None:
    sdk, device, _ = rig
    with pytest.raises(DeviceError, match="not connected"):
        await device.show(0, b"x")
    with pytest.raises(DeviceError, match="not connected"):
        await device.clear()
    sdk.plug(0x5548, 0x1000)
    await device.connect()
    sdk.created[0].image_result = -1
    with pytest.raises(DeviceError, match="setting key 0 failed"):
        await device.show(0, b"x")


async def test_presence_and_disconnect(rig: tuple[FakeSdk, M18Device, list[DeviceInput]]) -> None:
    sdk, device, _ = rig
    assert not await device.present()
    sdk.plug(0x5548, 0x1000, "/dev/hidraw7")
    assert await device.present()
    await device.connect()
    await device.clear()
    assert sdk.created[0].calls[-2:] == [("clear",), ("refresh",)]
    sdk.unplug()
    sdk.plug(0x5548, 0x1000, "/dev/hidraw9")  # a different device
    assert not await device.present()
    sdk.created[0].fail_close = True
    await device.disconnect()
    assert not device.connected
    await device.disconnect()  # idempotent


async def test_tries_ids_in_order(tmp_path: Path) -> None:
    sdk = FakeSdk()
    sdk.plug(0x6603, 0x1009, "/dev/second")
    device = M18Device(
        sdk, [(0x5548, 0x1000), (0x6603, 0x1009)], tmp_path, lambda e: None, access=lambda p: True
    )
    cwd = os.getcwd()
    try:
        assert await device.connect()
        assert sdk.created[0].info["path"] == "/dev/second"
    finally:
        await device.shutdown()
        os.chdir(cwd)
