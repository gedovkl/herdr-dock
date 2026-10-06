from pathlib import Path

import pytest

from herdr_core.config import ConfigError
from linux.config import (
    DEFAULT_HOME,
    HomeKey,
    LinuxConfig,
    load_linux_config,
    parse_linux_config,
)


def test_defaults() -> None:
    config = parse_linux_config({})
    assert config == LinuxConfig()
    assert config.home == DEFAULT_HOME
    assert config.buttons == {"left": "herdr", "middle": "none", "right": "page"}


def test_full(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    path.write_text(
        """
[linux]
brightness = 40
device_ids = ["5548:1000", "6603:1009"]
app_launcher = "gtk-launch {app}"
poll_seconds = 1
[linux.buttons]
middle = "herdr"
right = "none"

[[home]]
key = 1
label = "herdr"
herdr = true

[[home]]
key = 2
label = "Firefox"
app = "firefox"
icon = "~/icons/ff.png"

[[home]]
key = 15
label = "Build"
run = "make"
symbol = "⚙"
"""
    )
    config = load_linux_config(path)
    assert config.brightness == 40
    assert config.device_ids == ((0x5548, 0x1000), (0x6603, 0x1009))
    assert config.app_launcher == "gtk-launch {app}"
    assert config.poll_seconds == 1.0
    assert config.buttons == {"left": "herdr", "middle": "herdr", "right": "none"}
    assert config.home == (
        HomeKey(1, "herdr", herdr=True),
        HomeKey(2, "Firefox", app="firefox", icon=str(Path.home() / "icons/ff.png")),
        HomeKey(15, "Build", run="make", symbol="⚙"),
    )
    assert config.home[2].index == 14


def test_focus_keys() -> None:
    config = parse_linux_config(
        {
            "home": [
                {"key": 2, "label": "Browser", "app": "chromium", "focus": "^chromium$"},
                {"key": 3, "label": "Zed", "focus": "zed"},
            ]
        }
    )
    assert config.home == (
        HomeKey(2, "Browser", app="chromium", focus="^chromium$"),
        HomeKey(3, "Zed", focus="zed"),
    )


def test_missing_file_means_defaults(tmp_path: Path) -> None:
    assert load_linux_config(tmp_path / "none.toml") == LinuxConfig()


def test_invalid_toml(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    path.write_text("[linux")
    with pytest.raises(ConfigError):
        load_linux_config(path)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"linux": "x"}, r"\[linux\] must be a table"),
        ({"linux": {"brightness": 101}}, "brightness must be 0-100"),
        ({"linux": {"brightness": True}}, "brightness"),
        ({"linux": {"poll_seconds": 0}}, "poll_seconds"),
        ({"linux": {"app_launcher": "gtk-launch"}}, "containing {app}"),
        ({"linux": {"device_ids": "5548:1000"}}, "must be a list"),
        ({"linux": {"device_ids": ["5548"]}}, "VID:PID"),
        ({"linux": {"device_ids": ["zz:1000"]}}, "VID:PID"),
        ({"linux": {"buttons": "x"}}, r"\[linux.buttons\] must be a table"),
        ({"linux": {"buttons": {"top": "herdr"}}}, "unknown button 'top'"),
        ({"linux": {"buttons": {"left": "dance"}}}, "unknown action 'dance'"),
        ({"home": {"key": 1}}, "array of tables"),
        ({"home": ["x"]}, "must be a table"),
        ({"home": [{"key": 0, "herdr": True}]}, "home.key must be 1-15"),
        ({"home": [{"key": 16, "herdr": True}]}, "home.key must be 1-15"),
        ({"home": [{"key": 1, "herdr": True}, {"key": 1, "run": "x"}]}, "used twice"),
        ({"home": [{"key": 1}]}, "exactly one of run, app or herdr"),
        ({"home": [{"key": 1, "run": "a", "app": "b"}]}, "exactly one"),
        ({"home": [{"key": 1, "run": 3}]}, "run must be a string"),
        ({"home": [{"key": 1, "herdr": "yes"}]}, "herdr must be true or false"),
        ({"home": [{"key": 1, "herdr": True, "focus": "x"}]}, "can't be combined"),
        ({"home": [{"key": 1, "herdr": True, "run": "x"}]}, "can't be combined"),
        ({"home": [{"key": 1, "app": "a", "focus": "("}]}, "invalid focus pattern"),
    ],
)
def test_errors(data: dict[str, object], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        parse_linux_config(data)
