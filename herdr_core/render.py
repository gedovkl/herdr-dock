"""Draw key faces as square PNGs with Pillow."""

from __future__ import annotations

import io
import logging
import math
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import resources
from types import MappingProxyType

from PIL import Image, ImageDraw, ImageFont

from herdr_core.animation import SPINNER_FRAMES, Effect
from herdr_core.faces import (
    AgentFace,
    ClockFace,
    EmptyFace,
    ExitFace,
    Face,
    LauncherFace,
    OfflineFace,
    PagerFace,
    PomodoroFace,
    TimerFace,
    WeatherFace,
)
from herdr_core.models import AgentStatus
from herdr_core.theme import (
    CLOCK_DATE_COLOR,
    CLOCK_DAY_COLOR,
    CLOCK_TIME_COLOR,
    POMODORO_REST_COLOR,
    POMODORO_WORK_COLOR,
    STATUS_SYMBOL,
    STOPWATCH_FACE,
    STOPWATCH_HAND,
    STOPWATCH_RING,
    TIMER_RUNNING_COLOR,
    TOMATO_COLOR,
    TOMATO_HIGHLIGHT,
    TOMATO_LEAF_COLOR,
    WEATHER_COLOR,
    WEATHER_SYMBOL,
    temperature_color,
)

log = logging.getLogger(__name__)

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
        self._sized_fonts: dict[int, ImageFont.FreeTypeFont] = {}
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
        if isinstance(face, LauncherFace):
            return self._launcher(face)
        if isinstance(face, ClockFace):
            return self._clock_face(face)
        if isinstance(face, WeatherFace):
            return self._weather_face(face)
        if isinstance(face, PomodoroFace):
            return self._pomodoro_face(face)
        if isinstance(face, TimerFace):
            return self._timer_face(face)
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

    def _launcher(self, face: LauncherFace) -> Image.Image:
        image, draw = self._canvas(self._bg)
        fg = hex_to_rgb(self._palette.light_text)
        icon = self._load_icon(face.icon) if face.icon else None
        if icon is not None:
            image.paste(icon, ((self._size - icon.width) // 2, self._px(5)), icon)
        elif face.symbol:
            draw.text(
                (self._half, self._px(26)), face.symbol, font=self._symbol, fill=fg, anchor="mm"
            )
        self._line(draw, face.label, self._size - self._px(3), "mb", fg)
        return image

    def _clock_face(self, face: ClockFace) -> Image.Image:
        """Time on top; the date below, one row per line of `face.date` (at most two)."""
        image, draw = self._canvas(self._bg)
        fg = hex_to_rgb(CLOCK_TIME_COLOR)
        width = self._size - self._px(6)
        rows = [line for line in face.date.split("\n") if line][:2]
        # Two rows: day in an accent colour, date softer. One row: just the softer colour.
        row_colors = [CLOCK_DAY_COLOR, CLOCK_DATE_COLOR] if len(rows) == 2 else [CLOCK_DATE_COLOR]
        # (time y, time max size, date row ys, date max size) in 64 px units
        layouts = {0: (32, 22, (), 0), 1: (26, 22, (53,), 12), 2: (18, 20, (39, 54), 14)}
        time_y, time_size, row_ys, row_size = layouts[len(rows)]
        time_font = self._font_to_fit(face.time, width, largest=time_size, smallest=9)
        draw.text((self._half, self._px(time_y)), face.time, font=time_font, fill=fg, anchor="mm")
        for text, y, color in zip(rows, row_ys, row_colors[: len(rows)], strict=True):
            font = self._font_to_fit(text, width, largest=row_size, smallest=7)
            draw.text(
                (self._half, self._px(y)), text, font=font, fill=hex_to_rgb(color), anchor="mm"
            )
        return image

    def _weather_face(self, face: WeatherFace) -> Image.Image:
        image, draw = self._canvas(self._bg)
        fg = hex_to_rgb(self._palette.light_text)
        width = self._size - self._px(6)
        symbol = WEATHER_SYMBOL.get(face.condition, "")
        if symbol:
            color = hex_to_rgb(WEATHER_COLOR.get(face.condition, self._palette.light_text))
            position = (self._half, self._px(15))
            draw.text(position, symbol, font=self._symbol_small, fill=color, anchor="mm")
        temp_color = fg if face.celsius is None else hex_to_rgb(temperature_color(face.celsius))
        temp_font = self._font_to_fit(face.temperature, width, largest=20, smallest=9)
        temp_y = self._px(38) if symbol else self._px(28)
        draw.text(
            (self._half, temp_y), face.temperature, font=temp_font, fill=temp_color, anchor="mm"
        )
        if face.place:
            muted = blend(fg, hex_to_rgb(self._palette.muted), 0.4)
            self._line(draw, face.place, self._size - self._px(3), "mb", muted)
        return image

    def _pomodoro_face(self, face: PomodoroFace) -> Image.Image:
        image, draw = self._canvas(self._bg)
        if face.phase == "idle":
            self._draw_tomato(draw)
            self._line(draw, "pomodoro", self._size - self._px(3), "mb", self._soft_text())
            return image
        color = hex_to_rgb(POMODORO_WORK_COLOR if face.phase == "work" else POMODORO_REST_COLOR)
        label = "WORK" if face.phase == "work" else "REST"
        draw.text((self._half, self._px(11)), label, font=self._text, fill=color, anchor="mm")
        width = self._size - self._px(6)
        font = self._font_to_fit(face.remaining, width, largest=21, smallest=9)
        fg = hex_to_rgb(self._palette.light_text)
        draw.text((self._half, self._px(33)), face.remaining, font=font, fill=fg, anchor="mm")
        # progress bar
        left, right = self._px(6), self._size - self._px(6)
        top, bottom = self._size - self._px(12), self._size - self._px(7)
        draw.rounded_rectangle(
            (left, top, right, bottom), radius=self._px(2), fill=blend(self._bg, color, 0.25)
        )
        filled = left + round((right - left) * max(0.0, min(1.0, face.progress)))
        if filled > left:
            draw.rounded_rectangle((left, top, filled, bottom), radius=self._px(2), fill=color)
        return image

    def _draw_tomato(self, draw: ImageDraw.ImageDraw) -> None:
        cx, cy, r = self._half, self._px(30), self._px(17)
        draw.ellipse((cx - r, cy - r + self._px(1), cx + r, cy + r), fill=hex_to_rgb(TOMATO_COLOR))
        hx, hy, hr = cx - self._px(8), cy - self._px(3), self._px(4)
        draw.ellipse((hx - hr, hy - hr, hx + hr, hy + hr), fill=hex_to_rgb(TOMATO_HIGHLIGHT))
        # calyx: five green leaves radiating from the top of the tomato, plus a stem
        leaf = hex_to_rgb(TOMATO_LEAF_COLOR)
        base_x, base_y = cx, cy - r + self._px(4)
        for angle in (-160, -110, -70, -20, 90):
            rad = math.radians(angle)
            tip = (base_x + math.cos(rad) * self._px(11), base_y + math.sin(rad) * self._px(6))
            side = math.radians(angle + 90)
            half = self._px(2.5)
            p1 = (base_x + math.cos(side) * half, base_y + math.sin(side) * half)
            p2 = (base_x - math.cos(side) * half, base_y - math.sin(side) * half)
            draw.polygon([p1, tip, p2], fill=leaf)
        draw.line(
            (base_x, base_y, base_x + self._px(2), base_y - self._px(9)),
            fill=leaf,
            width=self._px(3),
        )

    def _timer_face(self, face: TimerFace) -> Image.Image:
        image, draw = self._canvas(self._bg)
        if not face.elapsed:
            self._draw_stopwatch(draw)
            self._line(draw, "timer", self._size - self._px(3), "mb", self._soft_text())
            return image
        color = hex_to_rgb(TIMER_RUNNING_COLOR)
        dot = self._px(3)
        if face.pulse:
            draw.ellipse(
                (self._half - dot, self._px(9) - dot, self._half + dot, self._px(9) + dot),
                fill=hex_to_rgb(POMODORO_WORK_COLOR),
            )
        width = self._size - self._px(6)
        font = self._font_to_fit(face.elapsed, width, largest=21, smallest=9)
        draw.text((self._half, self._px(33)), face.elapsed, font=font, fill=color, anchor="mm")
        self._line(draw, "timer", self._size - self._px(3), "mb", self._soft_text())
        return image

    def _draw_stopwatch(self, draw: ImageDraw.ImageDraw) -> None:
        cx, cy, r = self._half, self._px(30), self._px(17)
        # crown and side button
        crown = hex_to_rgb(STOPWATCH_RING[3])
        draw.rounded_rectangle(
            (cx - self._px(4), cy - r - self._px(7), cx + self._px(4), cy - r - self._px(2)),
            radius=self._px(1),
            fill=crown,
        )
        draw.rectangle(
            (cx - self._px(1), cy - r - self._px(3), cx + self._px(1), cy - r + self._px(1)),
            fill=crown,
        )
        # colourful ring: four arcs
        box = (cx - r, cy - r, cx + r, cy + r)
        for i, hex_color in enumerate(STOPWATCH_RING):
            start = -90 + i * 90
            draw.arc(box, start, start + 90, fill=hex_to_rgb(hex_color), width=self._px(4))
        inner = r - self._px(5)
        draw.ellipse(
            (cx - inner, cy - inner, cx + inner, cy + inner), fill=hex_to_rgb(STOPWATCH_FACE)
        )
        hand = hex_to_rgb(STOPWATCH_HAND)
        draw.line((cx, cy, cx, cy - inner + self._px(2)), fill=hand, width=self._px(2))
        draw.line(
            (cx, cy, cx + self._px(7), cy + self._px(4)),
            fill=hex_to_rgb(STOPWATCH_RING[1]),
            width=self._px(2),
        )
        draw.ellipse(
            (cx - self._px(2), cy - self._px(2), cx + self._px(2), cy + self._px(2)), fill=hand
        )

    def _soft_text(self) -> RGB:
        return blend(hex_to_rgb(self._palette.light_text), hex_to_rgb(self._palette.muted), 0.4)

    def _font_to_fit(
        self, text: str, width: int, *, largest: int, smallest: int
    ) -> ImageFont.FreeTypeFont:
        """The largest text font (in 64 px units) that fits `width`; the smallest if none does."""
        for size in range(largest, smallest - 1, -1):
            font = self._sized_font(size)
            if font.getlength(text) <= width:
                return font
        return self._sized_font(smallest)

    def _sized_font(self, size: int) -> ImageFont.FreeTypeFont:
        px = self._px(size)
        font = self._sized_fonts.get(px)
        if font is None:
            font = ImageFont.truetype(_font_path(self.TEXT_FONT), px)
            self._sized_fonts[px] = font
        return font

    def _load_icon(self, path: str) -> Image.Image | None:
        box = self._size - self._px(22)
        try:
            with Image.open(path) as source:
                icon = source.convert("RGBA")
        except (OSError, ValueError) as exc:
            log.warning("cannot load icon %s: %s", path, exc)
            return None
        icon.thumbnail((box, box), Image.Resampling.LANCZOS)
        return icon

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
