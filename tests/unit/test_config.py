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
        'herdr_socket = "/run/h.sock"\nlabel = "title"\nresync_seconds = 5\nbrightness = 70\n'
        '[raise]\nenabled = false\nlinux = "hyprctl dispatch focuswindow x"\nmacos = "osascript"\n'
    )
    assert load_config(path) == Config(
        herdr_socket="/run/h.sock",
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
