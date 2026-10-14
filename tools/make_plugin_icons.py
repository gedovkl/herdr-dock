"""Render the plugins' icons with the same KeyRenderer that draws the keys.

Usage: .venv/bin/python tools/make_plugin_icons.py
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from herdr_core.faces import LauncherFace
from herdr_core.render import KeyRenderer, _font_path

ROOT = Path(__file__).resolve().parent.parent
VSD_ICON = ROOT / "vsd/com.herdr.dock.sdPlugin/static/img/icon.png"
ELGATO_IMG = ROOT / "elgato/com.herdr.dock.sdPlugin/static/img"
GLYPH = "◐"


def face(size: int) -> Image.Image:
    return Image.open(io.BytesIO(KeyRenderer(size=size).render(LauncherFace("herdr", GLYPH))))


def mono(size: int) -> Image.Image:
    """White glyph on transparent: what the app's action and category lists expect."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    font = ImageFont.truetype(_font_path("DejaVuSans.ttf"), int(size * 0.9))
    ImageDraw.Draw(image).text(
        (size / 2, size / 2), GLYPH, font=font, fill=(255, 255, 255, 255), anchor="mm"
    )
    return image


def main() -> None:
    VSD_ICON.parent.mkdir(parents=True, exist_ok=True)
    VSD_ICON.write_bytes(KeyRenderer(size=144).render(LauncherFace("herdr", GLYPH)))
    print(f"wrote {VSD_ICON}")
    ELGATO_IMG.mkdir(parents=True, exist_ok=True)
    # name: (1x size, image builder); the @2x file is twice the size
    for name, size, build in (
        ("plugin-icon", 256, face),
        ("key", 72, face),
        ("category-icon", 28, mono),
        ("action-icon", 20, mono),
    ):
        build(size).save(ELGATO_IMG / f"{name}.png")
        build(size * 2).save(ELGATO_IMG / f"{name}@2x.png")
        print(f"wrote {ELGATO_IMG / name}.png and @2x")


if __name__ == "__main__":
    main()
