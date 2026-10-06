from pathlib import Path

import pytest

from herdr_core.config import (
    Config,
    ConfigError,
    RaiseConfig,
    default_config_path,
    load_config,
    parse_config,
)


def test_defaults() -> None:
    assert parse_config({}) == Config()


def test_full_config(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        'herdr_socket = "/run/h.sock"\nherdr_bin = "/opt/herdr"\nlabel = "title"\n'
        "resync_seconds = 5\nbrightness = 70\n"
        '[raise]\nenabled = false\nlinux = "hyprctl dispatch focuswindow x"\nmacos = "osascript"\n'
    )
    assert load_config(path) == Config(
        herdr_socket="/run/h.sock",
        herdr_bin="/opt/herdr",
        label="title",
        resync_seconds=5.0,
        raise_window=RaiseConfig(
            enabled=False, linux="hyprctl dispatch focuswindow x", macos="osascript"
        ),
    )


def test_missing_default_file_means_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert load_config() == Config()


def test_missing_explicit_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml")


def test_invalid_toml(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("label = ")
    with pytest.raises(ConfigError, match=r"config\.toml"):
        load_config(path)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"label": "emoji"}, "label must be"),
        ({"resync_seconds": 0}, "resync_seconds"),
        ({"resync_seconds": True}, "resync_seconds"),
        ({"resync_seconds": "5"}, "resync_seconds"),
        ({"herdr_socket": 5}, "herdr_socket must be a string"),
        ({"herdr_bin": 5}, "herdr_bin must be a string"),
        ({"raise": "yes"}, r"\[raise\] must be a table"),
        ({"raise": {"enabled": "yes"}}, "raise.enabled"),
        ({"raise": {"linux": ["a"]}}, "raise.linux must be a string"),
    ],
)
def test_validation_errors(data: dict[str, object], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        parse_config(data)


def test_default_config_path() -> None:
    home = Path("/home/u")
    assert default_config_path({}, home) == home / ".config/herdr-dock/config.toml"
    assert default_config_path({"XDG_CONFIG_HOME": "/x"}, home) == Path("/x/herdr-dock/config.toml")


def test_animation_and_colors() -> None:
    from herdr_core.animation import AnimationConfig
    from herdr_core.models import AgentStatus

    config = parse_config(
        {
            "animate": False,
            "blink_hz": 3,
            "spinner_fps": 8,
            "pulse_hz": 1,
            "attention": ["blocked", "done"],
            "colors": {"blocked": "#FF0000"},
        }
    )
    assert config.animation == AnimationConfig(
        enabled=False,
        blink_hz=3.0,
        spinner_fps=8.0,
        pulse_hz=1.0,
        attention=frozenset({AgentStatus.BLOCKED, AgentStatus.DONE}),
    )
    assert config.colors == {AgentStatus.BLOCKED: "#FF0000"}


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"animate": "yes"}, "animate must be"),
        ({"blink_hz": -1}, "blink_hz"),
        ({"attention": "blocked"}, "attention must be a list"),
        ({"attention": ["panicking"]}, "unknown status 'panicking'"),
        ({"colors": "red"}, r"\[colors\] must be a table"),
        ({"colors": {"blocked": "red"}}, "colors.blocked must be #rrggbb"),
        ({"colors": {"sad": "#ff0000"}}, "colors: unknown status"),
    ],
)
def test_animation_and_color_errors(data: dict[str, object], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        parse_config(data)
