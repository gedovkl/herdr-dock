"""Render the macOS plugin's icon with the same KeyRenderer that draws the keys.

Usage: .venv/bin/python tools/make_plugin_icons.py
"""

from __future__ import annotations

from pathlib import Path

from herdr_core.faces import LauncherFace
from herdr_core.render import KeyRenderer

ICON = Path(__file__).resolve().parent.parent / "macos/com.herdr.dock.sdPlugin/static/img/icon.png"


def main() -> None:
    ICON.parent.mkdir(parents=True, exist_ok=True)
    ICON.write_bytes(KeyRenderer(size=144).render(LauncherFace("herdr", "◐")))
    print(f"wrote {ICON}")


if __name__ == "__main__":
    main()
