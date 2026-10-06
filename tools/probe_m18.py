"""Hardware probe for the StreamDock M18 (dev tool, needs the device; not part of the package).

Answers DESIGN.md open items: which USB IDs, which key code each physical button sends
(including any non-LCD buttons), and how fast key images can be updated.

    .venv/bin/python tools/probe_m18.py [--listen 30] [--vid 0x5548 --pid 0x1000]
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

from StreamDock.Devices.StreamDockM18 import StreamDockM18
from StreamDock.Transport.LibUSBHIDAPI import LibUSBHIDAPI

from herdr_core.animation import Effect
from herdr_core.faces import AgentFace
from herdr_core.models import AgentStatus
from herdr_core.render import KeyRenderer

KNOWN_M18_IDS = [(0x6603, 0x1009), (0x6603, 0x1012), (0x5548, 0x1000)]


def find(ids: list[tuple[int, int]]) -> list[dict[str, object]]:
    found = []
    for vid, pid in ids:
        for info in LibUSBHIDAPI.enumerate_devices(vendor_id=vid, product_id=pid):
            print(f"found {vid:04x}:{pid:04x} path={info['path']} info={info}")
            found.append(info)
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vid", type=lambda v: int(v, 0))
    parser.add_argument("--pid", type=lambda v: int(v, 0))
    parser.add_argument("--listen", type=float, default=30.0, help="seconds to record key presses")
    parser.add_argument("--rounds", type=int, default=20, help="timing rounds")
    parser.add_argument("--skip-timing", action="store_true", help="only label keys and listen")
    parser.add_argument("--raw-all", action="store_true", help="print every packet the dock sends")
    args = parser.parse_args()

    ids = [(args.vid, args.pid)] if args.vid and args.pid else KNOWN_M18_IDS
    infos = find(ids)
    if not infos:
        print("no M18 found (is the udev rule installed? see scripts/install-linux.sh --udev)")
        return 1

    info = infos[0]
    device = StreamDockM18(LibUSBHIDAPI(LibUSBHIDAPI.create_device_info_from_dict(info)), info)
    workdir = Path(tempfile.mkdtemp(prefix="m18-probe-"))
    os.chdir(workdir)  # the SDK writes temporary JPEGs into the current directory
    if not device.open():
        print("open() failed (permissions?)")
        return 1
    device.init()
    print(f"firmware={device.firmware_version!r} serial={device.serial_number!r}")

    renderer = KeyRenderer(size=64)
    statuses = list(AgentStatus)
    paths = []
    for key in range(1, 16):
        face = AgentFace(f"key {key}", f"#{key}", statuses[key % len(statuses)])
        path = workdir / f"key{key}.png"
        path.write_bytes(renderer.render(face))
        paths.append(path)

    start = time.perf_counter()
    for key, path in enumerate(paths, start=1):
        device.set_key_image(key, str(path))
    device.refresh()
    print(f"all 15 keys + refresh: {(time.perf_counter() - start) * 1000:.0f} ms")
    if not args.skip_timing:
        measure(device, renderer, workdir, args.rounds)
        for key, path in enumerate(paths, start=1):
            device.set_key_image(key, str(path))
        device.refresh()
    listen(device, args.listen, args.raw_all)
    device.clearAllIcon()
    device.refresh()
    device.close()
    return 0


def measure(device: StreamDockM18, renderer: KeyRenderer, workdir: Path, rounds: int) -> None:

    frames = []
    face = AgentFace("spin", "timing", AgentStatus.WORKING)
    for frame in range(4):
        path = workdir / f"spin{frame}.png"
        path.write_bytes(renderer.render(face, Effect.SPIN, frame))
        frames.append(path)
    single, triple = [], []
    for n in range(rounds):
        t = time.perf_counter()
        device.set_key_image(1, str(frames[n % 4]))
        device.refresh()
        single.append(time.perf_counter() - t)
    for n in range(rounds):
        t = time.perf_counter()
        for key in (1, 2, 3):
            device.set_key_image(key, str(frames[(n + key) % 4]))
        device.refresh()
        triple.append(time.perf_counter() - t)
    for name, samples in (("1 key + refresh", single), ("3 keys + refresh", triple)):
        ms = [s * 1000 for s in samples]
        print(
            f"{name}: median {statistics.median(ms):.1f} ms, max {max(ms):.1f} ms "
            f"→ ~{1000 / statistics.median(ms):.0f} updates/s"
        )


def listen(device: StreamDockM18, seconds: float, raw_all: bool) -> None:
    def raw(_device: object, data: bytes) -> None:
        packet = bytes(data)
        if len(packet) >= 11 and packet[0:3] == b"ACK" and packet[5:7] == b"OK":
            print(
                f"  raw key code=0x{packet[9]:02x} ({packet[9]}) state=0x{packet[10]:02x}",
                flush=True,
            )
        elif raw_all:
            print(f"  other packet ({len(packet)} B): {packet[:24].hex(' ')}", flush=True)

    def decoded(_device: object, event: object) -> None:
        print(f"  decoded {event}", flush=True)

    device.set_raw_read_callback(raw)
    device.set_key_callback(decoded)
    print(f"\nPress buttons now; listening {seconds:.0f}s…")
    sys.stdout.flush()
    time.sleep(seconds)


if __name__ == "__main__":
    raise SystemExit(main())
