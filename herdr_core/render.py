"""Draw key faces as square PNGs with Pillow."""

from __future__ import annotations

import io
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import resources
from types import MappingProxyType

from PIL import Image, ImageDraw, ImageFont

from herdr_core.animation import SPINNER_FRAMES, Effect
from herdr_core.faces import AgentFace, EmptyFace, ExitFace, Face, OfflineFace, PagerFace
from herdr_core.models import AgentStatus
from herdr_core.theme import STATUS_SYMBOL

RGB = tuple[int, int, int]

# herdr's palette roles (src/client/shell.rs status_color): red, teal, yellow, green, overlay0.
DEFAULT_STATUS_COLORS: Mapping[AgentStatus, str] = MappingProxyType(
    {
        AgentStatus.BLOCKED: "#e64553",
        AgentStatus.DONE: "#179299",
        AgentStatus.WORKING: "#df8e1d",
        AgentStatus.IDLE: "#40a02b",
        AgentStatus.UNKNOWN: "#7c7f93",
    }
)

# Statuses drawn on a full-colour key; quiet ones get a dark key with a coloured symbol.
FILLED_STATUSES = frozenset({AgentStatus.BLOCKED, AgentStatus.DONE, AgentStatus.WORKING})


@dataclass(frozen=True, slots=True)
class Palette:
    status: Mapping[AgentStatus, str] = field(default_factory=lambda: DEFAULT_STATUS_COLORS)
    background: str = "#1e1e2e"
    empty: str = "#000000"
    light_text: str = "#eff1f5"
    dark_text: str = "#11111b"
    muted: str = "#6c7086"
    focus: str = "#ffffff"

    def with_status_colors(self, overrides: Mapping[AgentStatus, str]) -> Palette:
        merged = dict(self.status)
        merged.update(overrides)
        return Palette(
            MappingProxyType(merged),
            self.background,
            self.empty,
            self.light_text,
            self.dark_text,
            self.muted,
            self.focus,
        )


def hex_to_rgb(color: str) -> RGB:
    value = color.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"expected #rrggbb, got {color!r}")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def blend(a: RGB, b: RGB, amount: float) -> RGB:
    """Mix `amount` of b into a."""
    return (
        round(a[0] + (b[0] - a[0]) * amount),
        round(a[1] + (b[1] - a[1]) * amount),
        round(a[2] + (b[2] - a[2]) * amount),
    )


def luminance(color: RGB) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _font_path(name: str) -> str:
    return str(resources.files("herdr_core") / "fonts" / name)


class KeyRenderer:
    """Renders faces to PNG bytes, caching the most recent results."""

    SYMBOL_FONT = "DejaVuSans.ttf"
    TEXT_FONT = "DejaVuSansCondensed-Bold.ttf"

    def __init__(
        self, palette: Palette | None = None, size: int = 64, cache_size: int = 512
    ) -> None:
        if size < 32:
            raise ValueError("key images must be at least 32 px")
        self._palette = palette or Palette()
        self._size = size
        self._scale = size / 64
        self._cache: OrderedDict[tuple[Face, Effect, int], bytes] = OrderedDict()
        self._cache_size = cache_size
        self._symbol = ImageFont.truetype(_font_path(self.SYMBOL_FONT), self._px(30))
        self._symbol_small = ImageFont.truetype(_font_path(self.SYMBOL_FONT), self._px(24))
        self._dot = ImageFont.truetype(_font_path(self.SYMBOL_FONT), self._px(11))
        self._text = ImageFont.truetype(_font_path(self.TEXT_FONT), self._px(11))
        self._status_rgb = {s: hex_to_rgb(c) for s, c in self._palette.status.items()}
        self._bg = hex_to_rgb(self._palette.background)

    @property
    def size(self) -> int:
        return self._size

    def render(self, face: Face, effect: Effect = Effect.NONE, frame: int = 0) -> bytes:
        key = (face, effect, frame)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        buffer = io.BytesIO()
        self.render_image(face, effect, frame).save(buffer, format="PNG")
        png = buffer.getvalue()
        self._cache[key] = png
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return png

    def render_image(self, face: Face, effect: Effect = Effect.NONE, frame: int = 0) -> Image.Image:
        if isinstance(face, AgentFace):
            return self._agent(face, effect, frame)
        if isinstance(face, PagerFace):
            return self._pager(face, effect, frame)
        if isinstance(face, ExitFace):
            return self._exit(face, effect, frame)
        if isinstance(face, OfflineFace):
            return self._offline()
        assert isinstance(face, EmptyFace)
        return Image.new("RGB", (self._size, self._size), self._palette.empty)

    # -- faces --------------------------------------------------------------------------

    def _agent(self, face: AgentFace, effect: Effect, frame: int) -> Image.Image:
        color = self._status_rgb[face.status]
        filled = face.status in FILLED_STATUSES
        background = color if filled else self._bg
        symbol_color = self._contrast(background) if filled else color
        if effect is Effect.BLINK and frame == 1:
            background, symbol_color = self._bg, color
        elif effect is Effect.PULSE and frame == 1:
            background = blend(background, self._bg, 0.55)
            symbol_color = self._contrast(background) if filled else color

        symbol = STATUS_SYMBOL[face.status]
        if effect is Effect.SPIN:
            symbol = SPINNER_FRAMES[frame % len(SPINNER_FRAMES)]

        image, draw = self._canvas(background)
        text_color = self._contrast(background)
        self._line(draw, face.kind, self._px(3), "mt", text_color)
        draw.text(
            (self._half, self._px(31)), symbol, font=self._symbol, fill=symbol_color, anchor="mm"
        )
        self._line(draw, face.label, self._size - self._px(3), "mb", text_color)
        if face.focused:
            self._border(draw, hex_to_rgb(self._palette.focus))
        return image

    def _pager(self, face: PagerFace, effect: Effect, frame: int) -> Image.Image:
        background = self._attention_background(effect, frame)
        image, draw = self._canvas(background)
        fg = self._contrast(background)
        draw.text((self._half, self._px(22)), "▶", font=self._symbol_small, fill=fg, anchor="mm")
        self._line(draw, f"{face.page + 1}/{face.page_count}", self._px(39), "mm", fg)
        self._dots(draw, face.offpage, self._size - self._px(9), background)
        return image

    def _exit(self, face: ExitFace, effect: Effect, frame: int) -> Image.Image:
        background = self._attention_background(effect, frame)
        image, draw = self._canvas(background)
        fg = self._contrast(background) if face.connected else hex_to_rgb(self._palette.muted)
        draw.text((self._half, self._px(22)), "◀", font=self._symbol_small, fill=fg, anchor="mm")
        self._line(draw, "herdr" if face.connected else "offline", self._px(39), "mm", fg)
        self._dots(draw, face.statuses, self._size - self._px(9), background)
        return image

    def _offline(self) -> Image.Image:
        image, draw = self._canvas(hex_to_rgb(self._palette.empty))
        muted = hex_to_rgb(self._palette.muted)
        self._line(draw, "herdr", self._px(24), "mm", muted)
        self._line(draw, "offline", self._px(40), "mm", muted)
        return image

    # -- helpers ------------------------------------------------------------------------

    @property
    def _half(self) -> float:
        return self._size / 2

    def _px(self, value: float) -> int:
        return max(1, round(value * self._scale))

    def _canvas(self, background: RGB) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        image = Image.new("RGB", (self._size, self._size), background)
        return image, ImageDraw.Draw(image)

    def _contrast(self, background: RGB) -> RGB:
        light, dark = hex_to_rgb(self._palette.light_text), hex_to_rgb(self._palette.dark_text)
        return dark if luminance(background) > 0.28 else light

    def _attention_background(self, effect: Effect, frame: int) -> RGB:
        if frame == 1 and effect is Effect.BLINK:
            return self._status_rgb[AgentStatus.BLOCKED]
        if frame == 1 and effect is Effect.PULSE:
            return blend(self._bg, self._status_rgb[AgentStatus.DONE], 0.5)
        return self._bg

    def _line(self, draw: ImageDraw.ImageDraw, text: str, y: int, anchor: str, fill: RGB) -> None:
        fitted = self._fit(text, self._size - self._px(6))
        draw.text((self._half, y), fitted, font=self._text, fill=fill, anchor=anchor)

    def _fit(self, text: str, width: int) -> str:
        if self._text.getlength(text) <= width:
            return text
        while text and self._text.getlength(text + "…") > width:
            text = text[:-1]
        return text + "…"

    def _dots(
        self, draw: ImageDraw.ImageDraw, statuses: tuple[AgentStatus, ...], y: int, bg: RGB
    ) -> None:
        if not statuses:
            return
        gap = self._px(11)
        x = self._half - gap * (len(statuses) - 1) / 2
        for status in statuses:
            color = self._status_rgb[status]
            if color == bg:  # keep a blocked dot visible on the red blink frame
                color = self._contrast(bg)
            draw.text((x, y), "●", font=self._dot, fill=color, anchor="mm")
            x += gap

    def _border(self, draw: ImageDraw.ImageDraw, color: RGB) -> None:
        width = self._px(2)
        draw.rectangle((0, 0, self._size - 1, self._size - 1), outline=color, width=width)
