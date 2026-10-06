"""Render every key face and animation frame to PNGs: `python -m herdr_core.preview --out DIR`."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageDraw

from herdr_core.animation import Animator, Effect
from herdr_core.faces import (
    AgentFace,
    ClockFace,
    EmptyFace,
    ExitFace,
    Face,
    LauncherFace,
    OfflineFace,
    PagerFace,
    WeatherFace,
)
from herdr_core.models import AgentStatus
from herdr_core.render import KeyRenderer
from herdr_core.theme import STATUS_PRIORITY

SAMPLES: tuple[tuple[str, Face], ...] = (
    *((f"agent-{s.value}", AgentFace("claude", "herdr-dock", s)) for s in STATUS_PRIORITY),
    ("agent-blocked-focused", AgentFace("claude", "herdr-dock", AgentStatus.BLOCKED, True)),
    ("agent-idle-focused", AgentFace("codex", "api", AgentStatus.IDLE, True)),
    ("agent-long-label", AgentFace("opencode", "a-very-long-project-name", AgentStatus.WORKING)),
    ("pager", PagerFace(0, 3, (AgentStatus.DONE, AgentStatus.IDLE))),
    ("pager-blocked", PagerFace(1, 3, (AgentStatus.BLOCKED, AgentStatus.WORKING))),
    ("exit", ExitFace((AgentStatus.WORKING, AgentStatus.IDLE))),
    ("exit-blocked", ExitFace((AgentStatus.BLOCKED, AgentStatus.DONE, AgentStatus.IDLE))),
    ("exit-offline", ExitFace((), connected=False)),
    ("launcher", LauncherFace("herdr", "◐")),
    ("clock", ClockFace("14:07", "Mon 5 Oct")),
    ("clock-seconds", ClockFace("14:07:59", "05.10.2026")),
    ("weather", WeatherFace("52°F", "☀", "Nashua")),
    ("weather-snow", WeatherFace("-12°C", "❄", "Somewhere long")),
    ("weather-offline", WeatherFace("--", "", "Nashua")),
    ("empty", EmptyFace()),
    ("offline", OfflineFace()),
)


def render_samples(
    renderer: KeyRenderer, animator: Animator, out: Path
) -> list[tuple[str, list[Path]]]:
    """Write one PNG per sample and frame; returns (name, frame paths) per sample."""
    out.mkdir(parents=True, exist_ok=True)
    written: list[tuple[str, list[Path]]] = []
    for name, face in SAMPLES:
        effect = animator.effect(face)
        frames: list[Path] = []
        for frame in range(Animator.frame_count(effect)):
            suffix = "" if effect is Effect.NONE else f"-{effect.value}{frame}"
            path = out / f"{name}{suffix}.png"
            path.write_bytes(renderer.render(face, effect, frame))
            frames.append(path)
        written.append((name, frames))
    return written


def contact_sheet(rows: list[tuple[str, list[Path]]], zoom: int = 3) -> Image.Image:
    """All samples in a grid, one row per sample, frames left to right, scaled up."""
    first = Image.open(rows[0][1][0])
    cell = first.width * zoom
    label_width, pad = 170, 8
    columns = max(len(frames) for _, frames in rows)
    sheet = Image.new(
        "RGB",
        (label_width + columns * (cell + pad) + pad, len(rows) * (cell + pad) + pad),
        "#808080",  # mid gray so both the white focus border and black keys stand out
    )
    draw = ImageDraw.Draw(sheet)
    for row, (name, frames) in enumerate(rows):
        y = pad + row * (cell + pad)
        draw.text((pad, y + cell // 2), name, fill="#000000", anchor="lm")
        for column, path in enumerate(frames):
            image = Image.open(path).resize((cell, cell), Image.Resampling.NEAREST)
            sheet.paste(image, (label_width + column * (cell + pad), y))
    return sheet


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render all key faces to PNG files.")
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument("--size", type=int, default=64, help="key size in px (default: 64)")
    args = parser.parse_args(argv)
    try:
        renderer = KeyRenderer(size=args.size)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    rows = render_samples(renderer, Animator(), args.out)
    contact_sheet(rows).save(args.out / "sheet.png")
    print(f"wrote {sum(len(f) for _, f in rows)} key images and sheet.png to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
