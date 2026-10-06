"""Against the real StreamDock M18. Run with: scripts/test-integration.sh hardware

Stop the herdr-dock daemon first; only one process can drive the device.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from herdr_core.animation import Effect
from herdr_core.faces import AgentFace, ExitFace, LauncherFace
from herdr_core.models import AgentStatus
from herdr_core.render import KeyRenderer
from linux.config import DEFAULT_DEVICE_IDS
from linux.device import DeviceInput, M18Device, StreamDockSdk

pytestmark = pytest.mark.hardware


@pytest.fixture
async def device(tmp_path: Path) -> AsyncIterator[M18Device]:
    cwd = os.getcwd()
    inputs: list[DeviceInput] = []
    m18 = M18Device(StreamDockSdk(), DEFAULT_DEVICE_IDS, tmp_path, inputs.append)
    if not await m18.connect():
        await m18.shutdown()
        pytest.skip("no M18 plugged in")
    yield m18
    await m18.clear()
    await m18.shutdown()
    os.chdir(cwd)


async def test_enumerates_and_reports_presence(device: M18Device) -> None:
    assert device.connected
    assert await device.present()


async def test_draws_every_key_and_animates(device: M18Device) -> None:
    renderer = KeyRenderer()
    statuses = list(AgentStatus)
    await device.show(0, renderer.render(ExitFace((AgentStatus.BLOCKED,))))
    for key in range(1, 15):
        face = AgentFace("claude", f"key {key + 1}", statuses[key % len(statuses)])
        await device.show(key, renderer.render(face))
    await device.show(14, renderer.render(LauncherFace("done", "✓")))
    spinner = AgentFace("claude", "spin", AgentStatus.WORKING)
    for frame in range(8):
        await device.show(1, renderer.render(spinner, Effect.SPIN, frame % 4))
        await asyncio.sleep(0.05)
