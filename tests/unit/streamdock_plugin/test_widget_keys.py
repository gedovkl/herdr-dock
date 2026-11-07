from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from herdr_core.faces import (
    ClockFace,
    Face,
    LauncherFace,
    PomodoroFace,
    TimerFace,
    WeatherFace,
)
from linux.widgets import ClockWidget, PomodoroWidget, TimerWidget, WeatherWidget
from streamdock_plugin.widget_keys import (
    WIDGET_KINDS,
    WeatherDefaults,
    WidgetBuilder,
    WidgetKeys,
    mac_notify,
    plugin_notify,
)

PREFIX = "com.herdr.dock."


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Sent:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def __call__(self, message: str) -> None:
        self.messages.append(json.loads(message))

    def contexts(self) -> list[str]:
        return [m["context"] for m in self.messages]


def render(face: Face) -> bytes:
    return repr(face).encode()


class Apps:
    def __init__(self, focused: bool = False) -> None:
        self.focused = focused
        self.patterns: list[str] = []
        self.commands: list[str] = []

    async def focus(self, pattern: str) -> bool:
        self.patterns.append(pattern)
        return self.focused

    def run(self, command: str) -> None:
        self.commands.append(command)


def keys(
    builder: WidgetBuilder | None = None, apps: Apps | None = None
) -> tuple[WidgetKeys, Sent, Apps]:
    sent, apps = Sent(), apps or Apps()
    widget_keys = WidgetKeys(
        PREFIX,
        sent,
        render,
        builder or WidgetBuilder(),
        run=apps.run,
        focus=apps.focus,
    )
    return widget_keys, sent, apps


def faces(sent: Sent) -> list[str]:
    import base64

    return [
        base64.b64decode(m["payload"]["image"].split(",", 1)[1]).decode() for m in sent.messages
    ]


def test_it_handles_only_widget_actions() -> None:
    widget_keys, _, _ = keys()
    for kind in WIDGET_KINDS:
        assert widget_keys.handles(PREFIX + kind)
    assert not widget_keys.handles(PREFIX + "agent")
    assert not widget_keys.handles("other.plugin.clock")


def test_a_key_draws_when_it_appears() -> None:
    widget_keys, sent, _ = keys()
    widget_keys.appeared("t", PREFIX + "timer", {})
    assert sent.contexts() == ["t"]
    assert faces(sent) == [repr(TimerFace())]


def test_ticks_only_resend_keys_that_changed_and_only_visible_ones() -> None:
    clock = Clock()
    builder = WidgetBuilder(clock=clock)
    widget_keys, sent, _ = keys(builder)
    widget_keys.appeared("t", PREFIX + "timer", {})
    widget_keys.appeared("p", PREFIX + "pomodoro", {})
    sent.messages.clear()
    widget_keys.tick()
    assert sent.messages == []  # nothing changed

    asyncio.run(widget_keys.pressed("t", PREFIX + "timer", {}))
    assert sent.contexts() == ["t"]  # a press redraws at once
    sent.messages.clear()
    clock.now += 1
    widget_keys.disappeared("p")
    widget_keys.tick()
    assert sent.contexts() == ["t"]


def test_settings_change_rebuilds_the_widget_but_a_reappearance_keeps_it() -> None:
    clock = Clock()
    widget_keys, sent, _ = keys(WidgetBuilder(clock=clock))
    widget_keys.appeared("p", PREFIX + "pomodoro", {"work": "25"})
    asyncio.run(widget_keys.pressed("p", PREFIX + "pomodoro", {"work": "25"}))
    widget_keys.disappeared("p")
    widget_keys.appeared("p", PREFIX + "pomodoro", {"work": "25"})  # same settings: still running
    assert "work" in faces(sent)[-1]
    widget_keys.appeared("p", PREFIX + "pomodoro", {"work": "50"})  # new settings: fresh widget
    assert faces(sent)[-1] == repr(PomodoroFace())


def test_a_press_on_an_unknown_key_is_ignored() -> None:
    widget_keys, sent, _ = keys()
    asyncio.run(widget_keys.pressed("nope", PREFIX + "timer", {}))
    assert sent.messages == []


def test_an_app_key_focuses_its_window_else_runs_its_command() -> None:
    settings = {"label": "Zed", "symbol": "Z", "focus": "^dev\\.zed\\.Zed$", "command": "zeditor"}
    widget_keys, sent, apps = keys(apps=Apps(focused=True))
    widget_keys.appeared("a", PREFIX + "app", settings)
    assert faces(sent) == [repr(LauncherFace("Zed", "Z"))]
    asyncio.run(widget_keys.pressed("a", PREFIX + "app", settings))
    assert apps.patterns == ["^dev\\.zed\\.Zed$"] and apps.commands == []

    apps.focused = False
    asyncio.run(widget_keys.pressed("a", PREFIX + "app", settings))
    assert apps.commands == ["zeditor"]


def test_an_app_key_without_focus_just_runs_and_a_failing_focus_falls_back() -> None:
    class Broken(Apps):
        async def focus(self, pattern: str) -> bool:
            raise RuntimeError("no hyprctl")

    widget_keys, _, apps = keys(apps=Broken())
    widget_keys.appeared("a", PREFIX + "app", {"command": "foot"})
    asyncio.run(widget_keys.pressed("a", PREFIX + "app", {"command": "foot"}))
    assert apps.commands == ["foot"] and apps.patterns == []

    widget_keys.appeared("b", PREFIX + "app", {"focus": "foot", "command": "foot"})
    asyncio.run(widget_keys.pressed("b", PREFIX + "app", {"focus": "foot", "command": "foot"}))
    assert apps.commands == ["foot", "foot"]

    widget_keys.appeared("c", PREFIX + "app", {"label": "x"})  # nothing to run: no error
    asyncio.run(widget_keys.pressed("c", PREFIX + "app", {"label": "x"}))
    assert apps.commands == ["foot", "foot"]


def test_builder_reads_settings_with_defaults() -> None:
    builder = WidgetBuilder()
    clock = builder.build("clock", {})
    assert isinstance(clock, ClockWidget)
    face = clock.face()
    assert isinstance(face, ClockFace) and len(face.time) == 5
    twelve = builder.build("clock", {"hour12": True}).face()
    assert isinstance(twelve, ClockFace) and 1 <= int(twelve.time.split(":")[0]) <= 12
    assert isinstance(builder.build("timer", {}), TimerWidget)
    pomodoro = builder.build("pomodoro", {"work": "50", "rest": 10, "notify": "false"})
    assert isinstance(pomodoro, PomodoroWidget)
    bad = builder.build("pomodoro", {"work": "abc", "rest": "-3"})  # bad values: defaults
    assert isinstance(bad, PomodoroWidget)
    assert builder.build("nonsense", {}) is None


def test_pomodoro_notifies_through_the_builders_notifier() -> None:
    clock, notes = Clock(), []
    builder = WidgetBuilder(clock=clock, notify=lambda title, body: notes.append(title))
    widget = builder.build("pomodoro", {"work": "1", "rest": "1"})
    assert widget is not None
    widget.press()
    clock.now += 61
    widget.advance()
    assert notes == ["Pomodoro: rest"]
    quiet = WidgetBuilder(clock=clock, notify=lambda t, b: notes.append(t)).build(
        "pomodoro", {"work": "1", "rest": "1", "notify": False}
    )
    assert quiet is not None
    quiet.press()
    clock.now += 61
    quiet.advance()
    assert notes == ["Pomodoro: rest"]


def test_weather_uses_the_key_settings_then_the_defaults() -> None:
    builder = WidgetBuilder(weather=WeatherDefaults(42.76, -71.47, "celsius", "Nashua"))
    from_defaults = builder.build("weather", {})
    assert isinstance(from_defaults, WeatherWidget)
    assert "latitude=42.76" in from_defaults.url and "celsius" in from_defaults.url
    own = builder.build(
        "weather", {"latitude": "51.5", "longitude": "-0.12", "units": "fahrenheit", "place": "LDN"}
    )
    assert isinstance(own, WeatherWidget)
    assert "latitude=51.5" in own.url and "fahrenheit" in own.url
    assert own.face() == WeatherFace("--", place="LDN")


def test_weather_without_any_location_says_so() -> None:
    widget = WidgetBuilder().build("weather", {"place": "Home"})
    assert widget is not None and not isinstance(widget, WeatherWidget)
    assert widget.face() == WeatherFace("--", place="set location")
    assert widget.press() is False
    widget.advance()


async def test_weather_keys_refresh_in_the_background_and_stop_when_replaced() -> None:
    calls: list[str] = []
    gate = asyncio.Event()

    async def fetch(url: str) -> Any:
        calls.append(url)
        gate.set()
        return {"current": {"temperature_2m": 21.4, "weather_code": 0, "is_day": 1}}

    builder = WidgetBuilder(weather=WeatherDefaults(1.0, 2.0), fetch=fetch)
    widget_keys, sent, _ = keys(builder)
    widget_keys.appeared("w", PREFIX + "weather", {})
    await asyncio.wait_for(gate.wait(), 1)
    await asyncio.sleep(0)
    assert calls and "21°C" in faces(sent)[-1]
    widget_keys.appeared("w", PREFIX + "weather", {"latitude": 3, "longitude": 4})
    await asyncio.sleep(0)
    await widget_keys.close()


async def test_run_ticks_until_closed() -> None:
    clock = Clock()
    ticks: list[float] = []

    async def sleep(seconds: float) -> None:
        ticks.append(seconds)
        clock.now += seconds
        if len(ticks) >= 3:
            raise asyncio.CancelledError

    sent, apps = Sent(), Apps()
    widget_keys = WidgetKeys(
        PREFIX,
        sent,
        render,
        WidgetBuilder(clock=clock),
        run=apps.run,
        focus=apps.focus,
        sleep=sleep,
    )
    widget_keys.appeared("t", PREFIX + "timer", {})
    await widget_keys.pressed("t", PREFIX + "timer", {})
    sent.messages.clear()
    with contextlib.suppress(asyncio.CancelledError):
        await widget_keys.run()
    assert ticks == [1.0, 1.0, 1.0]
    assert len(sent.messages) == 2  # the timer's seconds changed on each completed tick


def test_a_failing_widget_does_not_stop_the_others() -> None:
    class Broken(TimerWidget):
        def advance(self) -> None:
            raise RuntimeError("boom")

        def face(self) -> Face:
            raise RuntimeError("boom")

    class Builder(WidgetBuilder):
        def build(self, kind: str, settings: dict[str, Any]) -> Any:
            return Broken() if kind == "timer" else super().build(kind, settings)

    widget_keys, sent, _ = keys(Builder())
    widget_keys.appeared("bad", PREFIX + "timer", {})
    widget_keys.appeared("ok", PREFIX + "clock", {})
    widget_keys.tick()
    assert sent.contexts() == ["ok"]


def test_unknown_kind_draws_nothing() -> None:
    class Builder(WidgetBuilder):
        def build(self, kind: str, settings: dict[str, Any]) -> Any:
            return None

    widget_keys, sent, _ = keys(Builder())
    widget_keys.appeared("x", PREFIX + "clock", {})
    asyncio.run(widget_keys.pressed("x", PREFIX + "clock", {}))
    assert sent.messages == []


def test_notifier_per_platform(monkeypatch: Any) -> None:
    import streamdock_plugin.widget_keys as module

    assert plugin_notify("darwin") is mac_notify
    assert plugin_notify("linux") is module.desktop_notify
    spawned: list[list[str]] = []

    def popen(argv: list[str], **_: Any) -> None:
        spawned.append(argv)

    monkeypatch.setattr(module.subprocess, "Popen", popen)
    mac_notify('Po"mo', "Take a break")
    assert spawned[0][:2] == ["osascript", "-e"]
    assert 'with title "Po\\"mo"' in spawned[0][2]

    def missing(argv: list[str], **_: Any) -> None:
        raise OSError("no osascript")

    monkeypatch.setattr(module.subprocess, "Popen", missing)
    mac_notify("a", "b")  # never raises


def test_weather_defaults_come_from_the_first_home_weather_key(tmp_path: Any) -> None:
    from streamdock_plugin.widget_keys import weather_defaults

    config = tmp_path / "config.toml"
    config.write_text(
        '[[home]]\nkey = 1\nlabel = "c"\nwidget = "clock"\n'
        '[[home]]\nkey = 2\nlabel = "w"\nwidget = "weather"\n'
        'latitude = 42.76\nlongitude = -71.47\nplace = "Nashua"\n'
    )
    assert weather_defaults(config) == WeatherDefaults(42.76, -71.47, "celsius", "Nashua")
    config.write_text('[[home]]\nkey = 1\nlabel = "c"\nwidget = "clock"\n')
    assert weather_defaults(config) is None
    config.write_text("[[home]]\nkey = 99\n")  # invalid: logged, no defaults
    assert weather_defaults(config) is None
    assert weather_defaults(tmp_path / "missing.toml") is None


def test_app_keys_focus_through_hyprland_only_on_linux() -> None:
    from streamdock_plugin.widget_keys import platform_apps

    run, focus = platform_apps("linux")
    assert callable(run) and focus is not None
    assert platform_apps("darwin")[1] is None
