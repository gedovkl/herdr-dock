"""herdr-dock plugin for the StreamDock app. The app runs this with its connection arguments."""

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
from macos.herdr_path import herdr_status_reader
from macos.lifecycle import VisibilityLifecycle
from macos.plugin import COLUMNS, ROWS, HerdrPlugin
from macos.raiser import macos_raiser
from macos.surface import StreamDockSurface
from macos.websocket import WebSocketTransport

log = logging.getLogger("herdr_dock.macos")

KEY_COUNT = COLUMNS * ROWS


@dataclass(frozen=True, slots=True)
class PluginArgs:
    port: int
    plugin_uuid: str
    register_event: str


def parse_args(argv: Sequence[str] | None = None) -> PluginArgs:
    """The app passes `-port N -pluginUUID X -registerEvent Y -info JSON`."""
    parser = argparse.ArgumentParser(prog="herdr-dock-plugin")
    parser.add_argument("-port", type=int, required=True)
    parser.add_argument("-pluginUUID", required=True)
    parser.add_argument("-registerEvent", required=True)
    parser.add_argument("-info", default="{}")  # app/device details; devices arrive as events too
    args = parser.parse_args(argv)
    return PluginArgs(args.port, args.pluginUUID, args.registerEvent)


async def run_plugin(
    args: PluginArgs,
    config: Config,
    socket: Path,
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
    layout = KeyLayout(exit_key=True)  # key 1 is the app's folder back key
    stack = build_herdr_stack(
        config,
        surface,
        macos_raiser(config.raise_window),
        socket,
        layout=layout,
        key_count=KEY_COUNT,
    )
    lifecycle = VisibilityLifecycle(
        lambda: start_herdr(stack.presenter, stack.session),
        lambda: stop_herdr(stack.presenter, stack.session),
    )
    plugin = HerdrPlugin(surface, lifecycle, stack.presenter, stack.session, layout)
    holder.append(plugin)
    transport.start()
    try:
        await closed.wait()
    finally:
        await plugin.close()
        transport.close()


def default_log_file() -> Path:
    return Path.home() / "Library" / "Logs" / "herdr-dock" / "plugin.log"


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    home = Path.home()
    # herdr finds ~/.config/herdr through $HOME and reports a temp-dir socket without it.
    os.environ.setdefault("HOME", str(home))
    configure_logging(verbose=False, log_file=default_log_file())
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
    asyncio.run(run_plugin(args, config, socket))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
