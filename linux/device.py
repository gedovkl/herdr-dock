"""StreamDock M18 adapter over the vendor Python SDK.

All SDK calls run on one worker thread. Key numbering is physical: 0 is top-left, left to
right, top to bottom. Presses are decoded from raw packets because the SDK's decoded key
numbers don't match its own image numbering on the M18.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)

KEY_COUNT = 15
BUTTON_CODES = {0x25: "left", 0x30: "middle", 0x31: "right"}


@dataclass(frozen=True, slots=True)
class KeyPressed:
    index: int


@dataclass(frozen=True, slots=True)
class ButtonPressed:
    name: str


DeviceInput = KeyPressed | ButtonPressed


def decode_packet(data: bytes) -> DeviceInput | None:
    """Turn a raw HID report into a press; releases and other packets give None."""
    if len(data) < 11 or data[0:3] != b"ACK" or data[5:7] != b"OK":
        return None
    code, state = data[9], data[10]
    if state != 0x01:
        return None
    if 1 <= code <= KEY_COUNT:
        return KeyPressed(code - 1)
    if code in BUTTON_CODES:
        return ButtonPressed(BUTTON_CODES[code])
    return None


class DeviceError(Exception):
    pass


class DevicePermissionError(DeviceError):
    pass


class SdkDevice(Protocol):
    """The parts of the vendor SDK's StreamDockM18 we use."""

    def open(self) -> Any: ...
    def init(self) -> None: ...
    def set_brightness(self, percent: int) -> Any: ...
    def set_key_image(self, key: int, path: str) -> Any: ...
    def refresh(self) -> Any: ...
    def clearAllIcon(self) -> Any: ...
    def close(self, notify: bool = True) -> Any: ...
    def set_raw_read_callback(self, callback: Callable[[Any, Any], None]) -> None: ...


class Sdk(Protocol):
    def enumerate(self, vendor_id: int, product_id: int) -> list[dict[str, Any]]: ...
    def create(self, info: dict[str, Any]) -> SdkDevice: ...


class StreamDockSdk:
    """The real vendor SDK (imported lazily so tests and macOS never load it)."""

    def enumerate(self, vendor_id: int, product_id: int) -> list[dict[str, Any]]:
        from StreamDock.Transport.LibUSBHIDAPI import LibUSBHIDAPI

        return list(LibUSBHIDAPI.enumerate_devices(vendor_id=vendor_id, product_id=product_id))

    def create(self, info: dict[str, Any]) -> SdkDevice:
        from StreamDock.Devices.StreamDockM18 import StreamDockM18
        from StreamDock.Transport.LibUSBHIDAPI import LibUSBHIDAPI

        transport = LibUSBHIDAPI(LibUSBHIDAPI.create_device_info_from_dict(info))
        device: SdkDevice = StreamDockM18(transport, info)
        return device


class M18Device:
    """Implements KeySurface for the M18 and reports presses through `on_input`."""

    def __init__(
        self,
        sdk: Sdk,
        ids: Sequence[tuple[int, int]],
        workdir: Path,
        on_input: Callable[[DeviceInput], None],
        *,
        brightness: int = 70,
        access: Callable[[str], bool] = lambda path: os.access(path, os.R_OK | os.W_OK),
        exists: Callable[[str], bool] = lambda path: os.path.exists(path),
    ) -> None:
        self._sdk = sdk
        self._ids = tuple(ids)
        self._workdir = workdir
        self._on_input = on_input
        self._brightness = brightness
        self._access = access
        self._exists = exists
        self._device: SdkDevice | None = None
        self._path = ""
        self._executor = concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix="m18")
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def connected(self) -> bool:
        return self._device is not None

    async def connect(self) -> bool:
        """Open the first matching M18. Returns False if none is plugged in."""
        self._loop = asyncio.get_running_loop()
        return bool(await self._call(self._connect))

    async def present(self) -> bool:
        """Whether the opened device (or any matching one, if none is open) is plugged in."""
        return bool(await self._call(self._present))

    def alive(self) -> bool:
        """Cheap check that the open device's node still exists (it vanishes on unplug)."""
        return self._device is not None and self._exists(self._path)

    async def show(self, key: int, png: bytes) -> None:
        """Draw a key. While no device is connected this is a no-op; reconnecting redraws."""
        await self._call(self._show, key, png)

    async def clear(self) -> None:
        await self._call(self._clear)

    async def disconnect(self, *, removed: bool = False) -> None:
        """Close the device. `removed`: it was unplugged, so send it nothing more."""
        await self._call(self._disconnect, removed)

    async def shutdown(self) -> None:
        await self.disconnect()
        self._executor.shutdown(wait=True)

    async def _call(self, fn: Callable[..., Any], *args: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, fn, *args)

    # -- worker thread ------------------------------------------------------------------

    def _find(self) -> dict[str, Any] | None:
        for vid, pid in self._ids:
            for info in self._sdk.enumerate(vid, pid):
                return info
        return None

    def _connect(self) -> bool:
        if self._device is not None:
            return True
        info = self._find()
        if info is None:
            return False
        path = str(info.get("path", ""))
        # The SDK reports success even when it can't open the device, so check first.
        if not self._access(path):
            raise DevicePermissionError(
                f"no read/write access to {path}; install the udev rule: "
                "scripts/install-linux.sh --udev"
            )
        self._workdir.mkdir(parents=True, exist_ok=True)
        os.chdir(self._workdir)  # the SDK writes temporary JPEGs into the working directory
        device = self._sdk.create(info)
        if not device.open():
            raise DeviceError(f"opening {path} failed")
        device.init()
        device.set_brightness(self._brightness)
        device.clearAllIcon()
        device.refresh()
        device.set_raw_read_callback(self._raw)
        self._device, self._path = device, path
        log.info("M18 connected at %s", path)
        return True

    def _present(self) -> bool:
        for vid, pid in self._ids:
            for info in self._sdk.enumerate(vid, pid):
                if not self._path or info.get("path") == self._path:
                    return True
        return False

    def _show(self, key: int, png: bytes) -> None:
        if not 0 <= key < KEY_COUNT:
            raise ValueError(f"key {key} out of range")
        device = self._writable()
        if device is None:
            return
        path = self._workdir / f"key{key}.png"
        path.write_bytes(png)
        if device.set_key_image(key + 1, str(path)) == -1:
            raise DeviceError(f"setting key {key} failed")
        device.refresh()

    def _clear(self) -> None:
        device = self._writable()
        if device is not None:
            device.clearAllIcon()
            device.refresh()

    def _disconnect(self, removed: bool = False) -> None:
        device, self._device, self._path = self._device, None, ""
        if device is None:
            return
        try:
            device.set_raw_read_callback(lambda *_: None)
            # After a physical removal the SDK's "disconnect" write can kill the process
            # natively (see the SDK's close()), so only send it for an intentional close.
            device.close(notify=not removed)
        except Exception:
            log.debug("error closing M18", exc_info=True)
        log.info("M18 %s", "unplugged" if removed else "disconnected")

    def _writable(self) -> SdkDevice | None:
        """The device if it's safe to write to it; never write to an unplugged device."""
        if self._device is None:
            return None
        if not self._exists(self._path):
            self._disconnect(removed=True)
            return None
        return self._device

    def _raw(self, _device: Any, data: Any) -> None:
        """Called on the SDK's reader thread."""
        event = decode_packet(bytes(data))
        if event is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(self._on_input, event)
