import io

import pytest
from PIL import Image

from herdr_core.animation import Effect
from herdr_core.faces import AgentFace, EmptyFace, ExitFace, OfflineFace, PagerFace
from herdr_core.models import AgentStatus
from herdr_core.render import (
    DEFAULT_STATUS_COLORS,
    KeyRenderer,
    Palette,
    blend,
    hex_to_rgb,
    luminance,
)

S = AgentStatus
BG = hex_to_rgb(Palette().background)


def pixels(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGB")


def corner(png: bytes) -> tuple[int, int, int]:
    return pixels(png).getpixel((5, 32))  # type: ignore[return-value]


def color(status: AgentStatus) -> tuple[int, int, int]:
    return hex_to_rgb(DEFAULT_STATUS_COLORS[status])


@pytest.fixture(scope="module")
def renderer() -> KeyRenderer:
    return KeyRenderer()


def test_png_size(renderer: KeyRenderer) -> None:
    image = pixels(renderer.render(EmptyFace()))
    assert image.size == (64, 64)
    assert renderer.size == 64


@pytest.mark.parametrize("status", [S.BLOCKED, S.DONE, S.WORKING])
def test_attention_statuses_fill_the_key(renderer: KeyRenderer, status: AgentStatus) -> None:
    assert corner(renderer.render(AgentFace("claude", "x", status))) == color(status)


@pytest.mark.parametrize("status", [S.IDLE, S.UNKNOWN])
def test_quiet_statuses_are_dark(renderer: KeyRenderer, status: AgentStatus) -> None:
    assert corner(renderer.render(AgentFace("claude", "x", status))) == BG


def test_blink_off_frame_inverts(renderer: KeyRenderer) -> None:
    face = AgentFace("claude", "x", S.BLOCKED)
    assert corner(renderer.render(face, Effect.BLINK, 0)) == color(S.BLOCKED)
    off = pixels(renderer.render(face, Effect.BLINK, 1))
    assert off.getpixel((5, 32)) == BG
    assert color(S.BLOCKED) in {c for _, c in off.getcolors(4096) or []}  # red symbol remains


def test_pulse_dims_background(renderer: KeyRenderer) -> None:
    face = AgentFace("claude", "x", S.DONE)
    assert corner(renderer.render(face, Effect.PULSE, 1)) == blend(color(S.DONE), BG, 0.55)
    quiet = AgentFace("claude", "x", S.IDLE)
    assert corner(renderer.render(quiet, Effect.PULSE, 1)) == blend(BG, BG, 0.55)


def test_spinner_frames_differ(renderer: KeyRenderer) -> None:
    face = AgentFace("claude", "x", S.WORKING)
    frames = {renderer.render(face, Effect.SPIN, n) for n in range(4)}
    assert len(frames) == 4


def test_focus_border(renderer: KeyRenderer) -> None:
    face = AgentFace("claude", "x", S.IDLE, focused=True)
    assert pixels(renderer.render(face)).getpixel((0, 0)) == (255, 255, 255)
    assert pixels(renderer.render(AgentFace("claude", "x", S.IDLE))).getpixel((0, 0)) == BG


def test_text_contrast_dark_on_yellow(renderer: KeyRenderer) -> None:
    image = pixels(renderer.render(AgentFace("claude", "x", S.WORKING)))
    dark = hex_to_rgb(Palette().dark_text)
    assert dark in {c for _, c in image.getcolors(4096) or []}


def test_long_labels_are_ellipsized(renderer: KeyRenderer) -> None:
    assert renderer._fit("short", 58) == "short"
    fitted = renderer._fit("a-very-long-project-name", 58)
    assert fitted.endswith("…") and len(fitted) < 20
    assert renderer._fit("WWWWWWWWWW", 1) == "…"


def test_pager_and_exit_blink_red(renderer: KeyRenderer) -> None:
    pager = PagerFace(0, 2, (S.BLOCKED,))
    assert corner(renderer.render(pager, Effect.NONE)) == BG
    assert corner(renderer.render(pager, Effect.BLINK, 1)) == color(S.BLOCKED)
    exit_face = ExitFace((S.BLOCKED, S.IDLE))
    assert corner(renderer.render(exit_face, Effect.BLINK, 1)) == color(S.BLOCKED)
    assert corner(renderer.render(exit_face, Effect.PULSE, 1)) == blend(BG, color(S.DONE), 0.5)


def test_summary_keys_draw_status_dots(renderer: KeyRenderer) -> None:
    image = pixels(renderer.render(PagerFace(0, 2, (S.DONE, S.IDLE))))
    found = {c for _, c in image.getcolors(4096) or []}
    assert color(S.DONE) in found and color(S.IDLE) in found
    empty_dots = pixels(renderer.render(ExitFace(())))
    assert color(S.IDLE) not in {c for _, c in empty_dots.getcolors(4096) or []}


def test_exit_offline_and_offline_and_empty(renderer: KeyRenderer) -> None:
    muted = hex_to_rgb(Palette().muted)
    exit_off = pixels(renderer.render(ExitFace((), connected=False)))
    assert muted in {c for _, c in exit_off.getcolors(4096) or []}
    offline = pixels(renderer.render(OfflineFace()))
    assert offline.getpixel((0, 0)) == (0, 0, 0)
    assert muted in {c for _, c in offline.getcolors(4096) or []}
    assert pixels(renderer.render(EmptyFace())).getcolors() == [(64 * 64, (0, 0, 0))]


def test_cache_returns_same_bytes_and_evicts() -> None:
    small = KeyRenderer(cache_size=2)
    first = small.render(EmptyFace())
    assert small.render(EmptyFace()) is first
    small.render(OfflineFace())
    small.render(EmptyFace())  # refresh: EmptyFace is now most recent
    small.render(AgentFace("claude", "x", S.IDLE))  # evicts OfflineFace
    assert small.render(EmptyFace()) is first
    assert len(small._cache) == 2


def test_larger_keys_scale() -> None:
    assert pixels(KeyRenderer(size=144).render(AgentFace("c", "x", S.DONE))).size == (144, 144)


def test_rejects_tiny_keys() -> None:
    with pytest.raises(ValueError):
        KeyRenderer(size=16)


def test_palette_overrides() -> None:
    palette = Palette().with_status_colors({S.BLOCKED: "#0000ff"})
    assert palette.status[S.IDLE] == DEFAULT_STATUS_COLORS[S.IDLE]
    png = KeyRenderer(palette).render(AgentFace("claude", "x", S.BLOCKED))
    assert corner(png) == (0, 0, 255)


def test_color_helpers() -> None:
    assert hex_to_rgb("#ff8000") == (255, 128, 0)
    with pytest.raises(ValueError):
        hex_to_rgb("#fff")
    assert blend((0, 0, 0), (255, 255, 255), 0.5) == (128, 128, 128)
    assert luminance((255, 255, 255)) == pytest.approx(1.0)
    assert luminance((0, 0, 0)) == 0


def test_launcher_with_symbol(renderer: KeyRenderer) -> None:
    from herdr_core.faces import LauncherFace

    image = pixels(renderer.render(LauncherFace("herdr", "◐")))
    assert image.getpixel((5, 5)) == BG
    light = hex_to_rgb(Palette().light_text)
    assert light in {c for _, c in image.getcolors(4096) or []}
    assert renderer.render(LauncherFace("herdr", "◐")) != renderer.render(LauncherFace("herdr"))


def test_launcher_with_icon(renderer: KeyRenderer, tmp_path: object) -> None:
    from pathlib import Path

    from herdr_core.faces import LauncherFace

    icon = Path(str(tmp_path)) / "icon.png"
    Image.new("RGBA", (200, 100), (0, 0, 255, 255)).save(icon)
    image = pixels(renderer.render(LauncherFace("app", "◐", str(icon))))
    assert image.getpixel((32, 20)) == (0, 0, 255)  # icon drawn, scaled into the top area


def test_launcher_with_broken_icon_falls_back(
    renderer: KeyRenderer, tmp_path: object, caplog: pytest.LogCaptureFixture
) -> None:
    from pathlib import Path

    from herdr_core.faces import LauncherFace

    broken = Path(str(tmp_path)) / "broken.png"
    broken.write_text("not an image")
    with_symbol = renderer.render(LauncherFace("app", "◐", str(broken)))
    assert with_symbol == renderer.render(LauncherFace("app", "◐"))
    assert "cannot load icon" in caplog.text


def test_clock_and_weather_faces_fit_their_text(renderer: KeyRenderer) -> None:
    from herdr_core.faces import ClockFace, WeatherFace

    for face in (
        ClockFace("14:07", "Mon 5 Oct"),
        ClockFace("14:07", "Mon\n5 Oct"),
        ClockFace("14:07", "a\nb\nc (only two rows are drawn)"),
        ClockFace("14:07:59"),
        ClockFace("a very long time format that cannot fit", "and a long date too, really"),
        WeatherFace("52°F", "sun", "Nashua", 11.0),
        WeatherFace("--"),
    ):
        image = pixels(renderer.render(face))
        assert image.size == (64, 64)
        assert image.getpixel((0, 0)) == BG
        assert len(image.getcolors(4096) or []) > 3  # text was drawn
    assert renderer.render(ClockFace("14:07")) != renderer.render(ClockFace("14:08"))


def test_widget_colours(renderer: KeyRenderer) -> None:
    from herdr_core.faces import ClockFace, WeatherFace
    from herdr_core.theme import (
        CLOCK_DAY_COLOR,
        CLOCK_TIME_COLOR,
        WEATHER_COLOR,
        temperature_color,
    )

    def colours(face: object) -> set[tuple[int, int, int]]:
        image = pixels(renderer.render(face))  # type: ignore[arg-type]
        return {c for _, c in image.getcolors(4096) or []}

    clock = colours(ClockFace("14:07", "Mon\n5 Oct"))
    assert hex_to_rgb(CLOCK_TIME_COLOR) in clock and hex_to_rgb(CLOCK_DAY_COLOR) in clock
    rain = colours(WeatherFace("18°C", "rain", "x", 18.0))
    assert hex_to_rgb(WEATHER_COLOR["rain"]) in rain
    assert hex_to_rgb(temperature_color(18.0)) in rain
    unknown = colours(WeatherFace("18°C", "tornado", "x"))  # unknown condition: no symbol
    assert hex_to_rgb(WEATHER_COLOR["rain"]) not in unknown


@pytest.mark.parametrize(
    ("celsius", "colour"),
    [
        (-20, "#b4befe"),
        (0, "#89dceb"),
        (10, "#94e2d5"),
        (20, "#a6e3a1"),
        (25, "#f9e2af"),
        (30, "#fab387"),
        (40, "#f38ba8"),
    ],
)
def test_temperature_colours(celsius: float, colour: str) -> None:
    from herdr_core.theme import temperature_color

    assert temperature_color(celsius) == colour
