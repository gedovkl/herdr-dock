"""herdr-dock plugin for the VSD Craft (StreamDock) app. The app runs this with its arguments."""

from __future__ import annotations

from collections.abc import Sequence

from herdr_core.faces import KeyLayout
from streamdock_plugin.runner import PluginSpec
from streamdock_plugin.runner import main as run_main
from vsd.grid import ACTION_UUID, COLUMNS, ROWS, M18Grid

SPEC = PluginSpec(
    action_uuid=ACTION_UUID,
    grid=M18Grid(),
    key_count=COLUMNS * ROWS,
    key_size=64,
    layout=KeyLayout(exit_key=True),  # key 1 is the app's folder back key
)


def main(argv: Sequence[str] | None = None) -> int:
    return run_main(lambda _args: SPEC, argv)


if __name__ == "__main__":
    raise SystemExit(main())
