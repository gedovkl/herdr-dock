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
focus_herdr_on_enter = false
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
    assert config.focus_herdr_on_enter is False
    assert LinuxConfig().focus_herdr_on_enter is True
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
        ({"linux": {"focus_herdr_on_enter": "yes"}}, "focus_herdr_on_enter"),
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
        ({"home": [{"key": 1}]}, "exactly one of run, app, herdr = true or widget"),
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


def test_relative_icons_resolve_against_the_config_folder(tmp_path: Path) -> None:
    """The daemon changes its working directory, so relative paths must not depend on it."""
    path = tmp_path / "config.toml"
    path.write_text('[[home]]\nkey = 1\nlabel = "x"\nrun = "x"\nicon = "icons/x.png"\n')
    assert load_linux_config(path).home[0].icon == str(tmp_path / "icons/x.png")
    absolute = parse_linux_config({"home": [{"key": 1, "run": "x", "icon": "/abs/x.png"}]})
    assert absolute.home[0].icon == "/abs/x.png"


def test_relative_icons_with_a_relative_config_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "config.toml").write_text(
        '[[home]]\nkey = 1\nlabel = "x"\nrun = "x"\nicon = "icons/x.png"\n'
    )
    monkeypatch.chdir(tmp_path)
    icon = load_linux_config(Path("config.toml")).home[0].icon  # e.g. --config config.toml
    assert icon == str(tmp_path / "icons/x.png")  # absolute, so the SDK's chdir can't break it


def test_widget_keys() -> None:
    config = parse_linux_config(
        {
            "home": [
                {"key": 5, "widget": "clock", "time_format": "%H:%M:%S", "date_format": ""},
                {
                    "key": 10,
                    "widget": "weather",
                    "latitude": 42.7654,
                    "longitude": -71.4676,
                    "units": "fahrenheit",
                    "place": "Nashua",
                    "refresh_minutes": 30,
                    "run": "xdg-open https://weather.gov",
                },
            ]
        }
    )
    clock, weather = config.home
    assert (clock.widget, clock.time_format, clock.date_format) == ("clock", "%H:%M:%S", "")
    assert (weather.widget, weather.latitude, weather.longitude) == ("weather", 42.7654, -71.4676)
    assert (weather.units, weather.place) == ("fahrenheit", "Nashua")
    assert weather.refresh_minutes == 30.0
    assert weather.run == "xdg-open https://weather.gov"
    minimal = {"key": 1, "widget": "weather", "latitude": 0, "longitude": 0}
    default = parse_linux_config({"home": [minimal]})
    assert (default.home[0].units, default.home[0].refresh_minutes) == ("celsius", 15.0)


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ({"widget": "radio"}, "widget must be one of clock, weather"),
        ({"widget": "weather", "longitude": 1}, "latitude as a number"),
        ({"widget": "weather", "latitude": 91, "longitude": 1}, "latitude as a number"),
        ({"widget": "weather", "latitude": 1, "longitude": True}, "longitude as a number"),
        ({"widget": "weather", "latitude": 1, "longitude": 1, "units": "kelvin"}, "units must be"),
        (
            {"widget": "weather", "latitude": 1, "longitude": 1, "refresh_minutes": 0.5},
            "refresh_minutes",
        ),
        ({"widget": "clock", "herdr": True}, "can't be combined"),
    ],
)
def test_widget_errors(entry: dict[str, object], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        parse_linux_config({"home": [{"key": 1, **entry}]})


def test_pomodoro_and_timer_keys() -> None:
    config = parse_linux_config(
        {
            "home": [
                {"key": 13, "widget": "pomodoro", "work_minutes": 50, "rest_minutes": 10},
                {"key": 14, "widget": "pomodoro", "notify": False},
                {"key": 15, "widget": "timer"},
            ]
        }
    )
    custom, default, timer = config.home
    assert (custom.work_minutes, custom.rest_minutes, custom.notify) == (50.0, 10.0, True)
    assert (default.work_minutes, default.rest_minutes, default.notify) == (25.0, 5.0, False)
    assert timer.widget == "timer"


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ({"widget": "pomodoro", "work_minutes": 0}, "work_minutes must be a positive"),
        ({"widget": "pomodoro", "rest_minutes": "5"}, "rest_minutes must be a positive"),
        ({"widget": "pomodoro", "notify": "yes"}, "notify must be true or false"),
    ],
)
def test_pomodoro_errors(entry: dict[str, object], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        parse_linux_config({"home": [{"key": 1, **entry}]})
