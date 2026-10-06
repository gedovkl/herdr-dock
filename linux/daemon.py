"""herdr-dock Linux daemon: `python -m linux.daemon`. Composition root for the M18 front end."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import signal
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

from herdr_core.animation import Animator
from herdr_core.client import HerdrSocketClient
from herdr_core.config import Config, ConfigError, RaiseConfig, load_config
from herdr_core.faces import KeyLayout
from herdr_core.ports import Raiser, Sleep
from herdr_core.presenter import DeckPresenter
from herdr_core.raise_window import raiser_from_config
from herdr_core.render import KeyRenderer, Palette
from herdr_core.session import HerdrSession
from herdr_core.socket_path import resolve_socket_path
from linux.config import HERDR_WINDOW, KEY_COUNT, LinuxConfig, load_linux_config
from linux.controller import DockController
from linux.device import DeviceInput, M18Device, StreamDockSdk
from linux.hyprland import HerdrWindowRaiser, WindowFocuser
from linux.launcher import ShellLauncher

log = logging.getLogger("herdr_dock")


class _Redraw:
    """Queue item: repaint the dock (after a replug), in order with key presses."""


_REDRAW = _Redraw()


def default_workdir(env: dict[str, str] | os._Environ[str] = os.environ) -> Path:
    base = env.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return Path(base) / "herdr-dock"


def linux_raiser(config: RaiseConfig) -> Raiser:
    """`herdr-window` (or nothing configured) focuses the herdr client's window on Hyprland."""
    if config.enabled and config.linux.strip() in ("", HERDR_WINDOW):
        return HerdrWindowRaiser()
    return raiser_from_config(config, platform="linux")


class Daemon:
    """Wires device ↔ controller and keeps the device connected across replugs."""

    def __init__(
        self,
        device: M18Device,
        controller: DockController,
        *,
        poll_seconds: float,
        alive_seconds: float = 0.25,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._device = device
        self._controller = controller
        self._poll = poll_seconds
        self._alive = alive_seconds
        self._sleep = sleep
        # Key presses and redraws share one queue so they never run concurrently.
        self._inputs: asyncio.Queue[DeviceInput | _Redraw] = asyncio.Queue()
        self._last_error = ""
        self._announced_wait = False

    def on_input(self, event: DeviceInput) -> None:
        """Device callback (already on the event loop)."""
        self._inputs.put_nowait(event)

    async def run(self, stop: asyncio.Event) -> None:
        handler = asyncio.create_task(self._handle_inputs(), name="inputs")
        watcher = asyncio.create_task(self._watch_device(), name="device-watch")
        try:
            await stop.wait()
        finally:
            for task in (handler, watcher):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            with contextlib.suppress(Exception):
                await self._controller.shutdown()
            with contextlib.suppress(Exception):
                await self._device.clear()
            await self._device.shutdown()

    async def _handle_inputs(self) -> None:
        while True:
            event = await self._inputs.get()
            try:
                if isinstance(event, _Redraw):
                    await self._controller.redraw()
                else:
                    await self._controller.handle(event)
            except Exception:
                log.exception("handling %s failed", event)

    async def _watch_device(self) -> None:
        """Connect when the M18 appears; notice an unplug within `alive_seconds`.

        Never raises: a missing, unplugged or inaccessible dock is a normal state, logged once.
        """
        while True:
            try:
                if self._device.connected:
                    await self._check_alive()
                    await self._sleep(self._alive)
                    continue
                await self._try_connect()
            except Exception as exc:  # keep watching whatever the SDK throws
                self._log_once(f"M18: {exc}")
            await self._sleep(self._poll)

    async def _check_alive(self) -> None:
        if not self._device.alive():
            await self._device.disconnect(removed=True)

    async def _try_connect(self) -> None:
        if await self._device.connect():
            self._last_error, self._announced_wait = "", False
            self._inputs.put_nowait(_REDRAW)
        elif not self._announced_wait:
            log.info("waiting for the M18 to be plugged in")
            self._announced_wait = True

    def _log_once(self, message: str) -> None:
        if message != self._last_error:
            log.error("%s", message)
            self._last_error = message


def build(
    config: Config, linux: LinuxConfig, socket: Path, workdir: Path
) -> tuple[Daemon, DockController]:
    renderer = KeyRenderer(Palette().with_status_colors(config.colors), size=64)
    layout = KeyLayout(exit_key=True)
    holder: list[Callable[[DeviceInput], None]] = []
    device = M18Device(
        StreamDockSdk(),
        linux.device_ids,
        workdir,
        lambda event: holder[0](event),
        brightness=linux.brightness,
    )
    presenter = DeckPresenter(
        device, renderer, Animator(config.animation), layout=layout, label=config.label
    )
    client = HerdrSocketClient(socket)
    session = HerdrSession(
        client,
        client,
        linux_raiser(config.raise_window),
        capacity=layout.session_capacity(KEY_COUNT),
        on_view=presenter.update,
        resync_interval=config.resync_seconds,
    )
    controller = DockController(
        device,
        renderer,
        linux.home,
        ShellLauncher(linux.app_launcher),
        session,
        presenter,
        layout=layout,
        buttons=dict(linux.buttons),
        focuser=WindowFocuser(),
        on_enter=HerdrWindowRaiser().raise_herdr_window if linux.focus_herdr_on_enter else None,
    )
    daemon = Daemon(device, controller, poll_seconds=linux.poll_seconds)
    holder.append(daemon.on_input)
    return daemon, controller


async def serve(daemon: Daemon) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await daemon.run(stop)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="herdr-dock", description="herdr agents on a StreamDock M18"
    )
    parser.add_argument("--config", type=Path, help="config file (default: ~/.config/herdr-dock)")
    parser.add_argument("--socket", help="herdr socket path (default: auto-detect)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("PIL").setLevel(logging.INFO)  # chunk-level PNG debug noise
    try:
        config = load_config(args.config)
        linux = load_linux_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    # Absolute now: the device later changes the working directory for the SDK.
    socket = resolve_socket_path(
        args.socket or config.herdr_socket, os.environ, Path.home()
    ).absolute()
    log.info("herdr socket: %s", socket)
    daemon, _ = build(config, linux, socket, default_workdir())
    asyncio.run(serve(daemon))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
