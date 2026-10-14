"""herdr-dock plugin for the Elgato Stream Deck app. The app runs this with its arguments."""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from pathlib import Path

from elgato.config import (
    ElgatoConfig,
    choose_size,
    devices_from_info,
    load_elgato_config,
)
from elgato.grid import ACTION_UUID, ElgatoGrid
from herdr_core.config import ConfigError, default_config_path
from herdr_core.faces import KeyLayout
from streamdock_plugin.runner import GridReload, PluginArgs, PluginSpec
from streamdock_plugin.runner import main as run_main

log = logging.getLogger("herdr_dock.elgato")

RESTART_ONLY = ("columns", "rows", "key_size", "corner_radius", "folder")
"""Settings read once at start: they size the session and the renderer."""


def make_spec(args: PluginArgs) -> PluginSpec:
    path = default_config_path(os.environ, Path.home())
    try:
        config = load_elgato_config(explicit=False)
    except ConfigError as exc:
        log.error("%s; using the defaults", exc)
        config = ElgatoConfig()
    columns, rows = choose_size(config, devices_from_info(args.info))
    log.info(
        "serving a %sx%s dock (%s%s, %s), %s px keys",
        columns,
        rows,
        "portrait" if config.portrait else "landscape",
        ", mirrored" if config.mirror else "",
        "folder: key 1 is the back key" if config.folder else "no folder",
        config.key_size,
    )
    return PluginSpec(
        action_uuid=ACTION_UUID,
        grid=ElgatoGrid(
            columns, rows, portrait=config.portrait, mirror=config.mirror, back_key=config.folder
        ),
        key_count=columns * rows,
        key_size=config.key_size,
        corner_radius=config.corner_radius,
        layout=KeyLayout(exit_key=config.folder),  # the app's back key is key 1 in a folder
        reload=GridReload(path, lambda: reloaded_grid(path, config, (columns, rows))),
    )


def reloaded_grid(path: Path, started_with: ElgatoConfig, size: tuple[int, int]) -> ElgatoGrid:
    """The grid for the config as it is now: `portrait` and `mirror` apply, the rest waits."""
    config = load_elgato_config(
        path, explicit=False
    )  # a broken file raises: the caller keeps the old
    stale = [name for name in RESTART_ONLY if getattr(config, name) != getattr(started_with, name)]
    if stale:
        log.warning("restart the Stream Deck app to apply: %s", ", ".join(stale))
    log.info(
        "layout now %s%s",
        "portrait" if config.portrait else "landscape",
        ", mirrored" if config.mirror else "",
    )
    return ElgatoGrid(
        *size, portrait=config.portrait, mirror=config.mirror, back_key=started_with.folder
    )


def main(argv: Sequence[str] | None = None) -> int:
    return run_main(make_spec, argv, log_name="elgato-plugin.log")


if __name__ == "__main__":
    raise SystemExit(main())
