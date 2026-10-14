"""Entry point shared by the StreamDock-style plugins (the app passes the connection arguments)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import websocket

from herdr_core.config import Config, ConfigError, load_config
from herdr_core.faces import KeyLayout
from herdr_core.socket_path import resolve_socket_path
from herdr_core.wiring import build_herdr_stack, configure_logging, start_herdr, stop_herdr
from streamdock_plugin.grid import Grid
from streamdock_plugin.herdr_path import herdr_status_reader
from streamdock_plugin.lifecycle import VisibilityLifecycle
from streamdock_plugin.plugin import HerdrPlugin
from streamdock_plugin.raiser import macos_raiser
from streamdock_plugin.surface import StreamDockSurface
from streamdock_plugin.watch import FileWatcher
from streamdock_plugin.websocket import WebSocketTransport

log = logging.getLogger("herdr_dock.plugin")


@dataclass(frozen=True, slots=True)
class GridReload:
    """Re-number the keys when `path` changes. `load` returns the new grid or raises."""

    path: Path
    load: Callable[[], Grid]
    interval: float = 1.0


@dataclass(frozen=True, slots=True)
class PluginSpec:
    """What one front end (vsd/, elgato/) contributes: its action, grid and key layout."""

    action_uuid: str
    grid: Grid
    key_count: int
    key_size: int
    layout: KeyLayout
    corner_radius: float = 0.0
    reload: GridReload | None = None


@dataclass(frozen=True, slots=True)
class PluginArgs:
    port: int
    plugin_uuid: str
    register_event: str
    info: str = "{}"
    """The app's `-info` JSON: application, colours, devices (maybe not connected), plugin."""


def parse_args(argv: Sequence[str] | None = None) -> PluginArgs:
    """The app passes `-port N -pluginUUID X -registerEvent Y -info JSON`."""
    parser = argparse.ArgumentParser(prog="herdr-dock-plugin")
    parser.add_argument("-port", type=int, required=True)
    parser.add_argument("-pluginUUID", required=True)
    parser.add_argument("-registerEvent", required=True)
    parser.add_argument("-info", default="{}")  # devices also arrive later as events
    args = parser.parse_args(argv)
    return PluginArgs(args.port, args.pluginUUID, args.registerEvent, args.info)


async def run_plugin(
    args: PluginArgs,
    config: Config,
    socket: Path,
    spec: PluginSpec,
    *,
    app_factory: Callable[..., Any] = websocket.WebSocketApp,
) -> None:
    """Connect to the app and serve until it closes the connection."""
    loop = asyncio.get_running_loop()
    closed = asyncio.Event()
    holder: list[HerdrPlugin] = []
    transport = WebSocketTransport(
        args.port,
        args.register_event,
        args.plugin_uuid,
        loop,
        on_message=lambda raw: holder[0].handle(raw),
        on_close=closed.set,
        app_factory=app_factory,
    )
    surface = StreamDockSurface(transport)
    layout = spec.layout
    stack = build_herdr_stack(
        config,
        surface,
        macos_raiser(config.raise_window),
        socket,
        layout=layout,
        key_count=spec.key_count,
        key_size=spec.key_size,
        corner_radius=spec.corner_radius,
    )
    lifecycle = VisibilityLifecycle(
        lambda: start_herdr(stack.presenter, stack.session),
        lambda: stop_herdr(stack.presenter, stack.session),
    )
    plugin = HerdrPlugin(
        surface, lifecycle, stack.presenter, stack.session, layout, spec.grid, spec.action_uuid
    )
    holder.append(plugin)
    transport.start()
    watcher = _watch_grid(spec.reload, plugin)
    try:
        await closed.wait()
    finally:
        if watcher is not None:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        await plugin.close()
        transport.close()


def _watch_grid(reload: GridReload | None, plugin: HerdrPlugin) -> asyncio.Task[None] | None:
    if reload is None:
        return None

    def changed() -> None:
        try:
            grid = reload.load()
        except Exception as exc:  # a half-edited file is normal: keep the current layout
            log.warning("could not reload %s: %s; keeping the current layout", reload.path, exc)
            return
        plugin.set_grid(grid)
        log.info("reloaded %s: keys renumbered", reload.path)

    watcher = FileWatcher(reload.path, changed, interval=reload.interval)
    return asyncio.create_task(watcher.run(), name="config-watch")


def default_log_file(name: str) -> Path:
    return Path.home() / "Library" / "Logs" / "herdr-dock" / name


SpecFactory = Callable[[PluginArgs], PluginSpec]


def main(
    make_spec: SpecFactory, argv: Sequence[str] | None = None, *, log_name: str = "plugin.log"
) -> int:
    """Run a front end. `make_spec` runs once logging is up, so it can log and read config."""
    args = parse_args(argv)
    home = Path.home()
    # herdr finds ~/.config/herdr through $HOME and reports a temp-dir socket without it.
    os.environ.setdefault("HOME", str(home))
    configure_logging(verbose=False, log_file=default_log_file(log_name))
    try:
        config = load_config()
    except ConfigError as exc:
        log.error("%s; using the defaults", exc)  # no terminal to print to: the log is the report
        config = Config()
    socket = resolve_socket_path(
        config.herdr_socket,
        os.environ,
        home,
        herdr_status_reader(os.environ.get("PATH", ""), home, config.herdr_bin),
    ).absolute()
    log.info("herdr socket: %s", socket)
    asyncio.run(run_plugin(args, config, socket, make_spec(args)))
    return 0
