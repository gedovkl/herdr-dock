"""Action icons for the widget keys, rendered from their real key faces.

`python -m streamdock_plugin.icons DIR` writes `widget-<kind>.png` for every widget action
(scripts/install-opendeck-plugin.sh uses it, so the action list shows what the key looks like).
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from herdr_core.faces import ClockFace, Face, LauncherFace, PomodoroFace, TimerFace, WeatherFace
from herdr_core.render import KeyRenderer

ICON_FACES: dict[str, Face] = {
    "clock": ClockFace("12:00", "Mon\n1 Jan"),
    "weather": WeatherFace("21°C", "sun", "", 21.0),
    "pomodoro": PomodoroFace(),
    "timer": TimerFace(),
    "app": LauncherFace("App", "▶"),
}


def write_icons(directory: Path, size: int = 144, corner_radius: float = 0.15) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    renderer = KeyRenderer(size=size, corner_radius=corner_radius)
    written = []
    for kind, face in ICON_FACES.items():
        path = directory / f"widget-{kind}.png"
        path.write_bytes(renderer.render(face))
        written.append(path)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python -m streamdock_plugin.icons DIR", file=sys.stderr)
        return 2
    for path in write_icons(Path(args[0])):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
