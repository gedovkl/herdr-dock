from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from elgato.config import ElgatoConfig
from elgato.grid import ACTION_UUID, ElgatoGrid
from elgato.plugin_main import make_spec, reloaded_grid
from herdr_core.config import Config, ConfigError
from herdr_core.faces import KeyLayout
from streamdock_plugin.lifecycle import VisibilityLifecycle
from streamdock_plugin.plugin import HerdrPlugin
from streamdock_plugin.runner import GridReload, PluginArgs, PluginSpec, run_plugin
from streamdock_plugin.surface import StreamDockSurface

PHONE_PORTRAIT = ElgatoGrid(5, 3, portrait=True, back_key=True)
PHONE_SIDEWAYS_MIRRORED = ElgatoGrid(5, 3, mirror=True, back_key=True)


class Transport:
    def send(self, message: str) -> None: ...


class Presenter:
    def __init__(self) -> None:
        self.invalidated = 0

    def invalidate(self) -> None:
        self.invalidated += 1


class Session:
    async def press(self, key_index: int) -> None: ...


def appear(context: str, column: int, row: int) -> str:
    return json.dumps(
        {
            "event": "willAppear",
            "action": ACTION_UUID,
            "context": context,
            "device": "phone",
            "payload": {"coordinates": {"column": column, "row": row}},
        }
    )


async def nothing() -> None: ...


def make_plugin(grid: ElgatoGrid) -> tuple[HerdrPlugin, StreamDockSurface, Presenter]:
    surface, presenter = StreamDockSurface(Transport()), Presenter()
    lifecycle = VisibilityLifecycle(nothing, nothing, grace=0)
    plugin = HerdrPlugin(
        surface, lifecycle, presenter, Session(), KeyLayout(exit_key=True), grid, ACTION_UUID
    )
    return plugin, surface, presenter


async def test_keys_on_screen_are_renumbered_when_the_grid_changes() -> None:
    plugin, surface, presenter = make_plugin(PHONE_PORTRAIT)
    cells = {"a": (0, 2), "b": (0, 1), "c": (1, 2), "d": (4, 0)}
    for context, (column, row) in cells.items():
        plugin.handle(appear(context, column, row))
    before = {context: surface.key_of(context) for context in cells}
    assert before == {"a": 1, "b": 2, "c": 3, "d": 14}

    drawn = presenter.invalidated
    plugin.set_grid(PHONE_SIDEWAYS_MIRRORED)
    after = {context: surface.key_of(context) for context in cells}
    # Sideways and mirrored: the back key first, then each row right to left, so app (0, 2) is last.
    assert after == {"a": 14, "b": 9, "c": 13, "d": 1}
    assert presenter.invalidated > drawn  # everything is redrawn on its new key
    assert surface.count == 4
    await plugin.close()


async def test_a_key_that_leaves_the_grid_stops_drawing_and_can_come_back() -> None:
    plugin, surface, _ = make_plugin(ElgatoGrid(5, 3, back_key=True))
    plugin.handle(appear("a", 2, 1))
    assert surface.key_of("a") == 7
    plugin.set_grid(ElgatoGrid(2, 2, back_key=True))  # (2, 1) is now off the grid
    assert surface.key_of("a") is None
    plugin.set_grid(ElgatoGrid(5, 3, back_key=True))
    assert surface.key_of("a") == 7
    await plugin.close()


async def test_a_key_that_disappeared_is_not_brought_back_by_a_new_grid() -> None:
    plugin, surface, _ = make_plugin(PHONE_PORTRAIT)
    plugin.handle(appear("a", 0, 2))
    plugin.handle(
        json.dumps({"event": "willDisappear", "context": "a", "device": "phone", "action": ""})
    )
    plugin.set_grid(PHONE_SIDEWAYS_MIRRORED)
    assert surface.count == 0
    await plugin.close()


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return tmp_path


def write_config(home: Path, text: str) -> Path:
    path = home / ".config" / "herdr-dock" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_the_spec_watches_the_config_file(home: Path) -> None:
    spec = make_spec(PluginArgs(1, "u", "r", "{}"))
    assert spec.reload is not None
    assert spec.reload.path == home / ".config" / "herdr-dock" / "config.toml"


def test_a_reload_applies_portrait_and_mirror(home: Path) -> None:
    path = write_config(home, "[elgato]\nportrait = true\n")
    started = ElgatoConfig(portrait=True)
    write_config(home, "[elgato]\nmirror = true\n")
    grid = reloaded_grid(path, started, (5, 3))
    assert grid.key_index(0, 0) == 0  # the folder's back key stays first
    assert grid.key_index(4, 0) == 1  # now landscape and mirrored: first agent at the top-left


def test_a_reload_warns_about_settings_that_need_a_restart(
    home: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = write_config(home, "[elgato]\nkey_size = 72\nfolder = false\ncorner_radius = 0\n")
    grid = reloaded_grid(path, ElgatoConfig(), (5, 3))
    assert "restart the Stream Deck app to apply: key_size, corner_radius, folder" in caplog.text
    assert grid.key_index(0, 0) == 0  # still serving as a folder: the back key stays reserved


def test_a_broken_file_raises_so_the_caller_keeps_the_old_layout(home: Path) -> None:
    path = write_config(home, "[elgato]\ncolumns = 3\n")  # rows missing
    with pytest.raises(ConfigError):
        reloaded_grid(path, ElgatoConfig(), (5, 3))


class WatchedApp:
    """A fake app that shows one key, then stays connected until released."""

    def __init__(self, url: str, **callbacks: Callable[..., None]) -> None:
        self.callbacks = callbacks
        self.sent: list[dict[str, Any]] = []
        self.release = threading.Event()

    def run_forever(self) -> None:
        self.callbacks["on_open"](self)
        self.callbacks["on_message"](self, appear("a", 0, 2))
        self.release.wait(5)
        self.callbacks["on_close"](self, 1000, "bye")

    def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    def close(self) -> None:
        self.release.set()


async def test_the_runner_renumbers_keys_when_the_watched_file_changes(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("v1")
    grids = [PHONE_PORTRAIT, PHONE_SIDEWAYS_MIRRORED]
    spec = PluginSpec(
        action_uuid=ACTION_UUID,
        grid=grids[0],
        key_count=15,
        key_size=72,
        layout=KeyLayout(exit_key=True),
        reload=GridReload(config_file, lambda: grids[1], interval=0.01),
    )
    apps: list[WatchedApp] = []

    def factory(url: str, **callbacks: Callable[..., None]) -> WatchedApp:
        apps.append(WatchedApp(url, **callbacks))
        return apps[0]

    task = asyncio.create_task(
        run_plugin(
            PluginArgs(1, "u", "register"),
            Config(),
            tmp_path / "no.sock",
            spec,
            app_factory=factory,
        )
    )

    def image_contexts() -> int:
        return sum(1 for m in apps[0].sent if m["event"] == "setImage") if apps else 0

    async def until(condition: Callable[[], bool]) -> None:
        for _ in range(300):
            if condition():
                return
            await asyncio.sleep(0.01)
        raise AssertionError("timed out")

    await until(lambda: image_contexts() >= 1)
    drawn = image_contexts()
    config_file.write_text("version two")  # a different size and time: the watcher notices
    await until(lambda: image_contexts() > drawn)  # redrawn on the new key
    apps[0].release.set()
    await asyncio.wait_for(task, 5)


async def test_a_failing_reload_keeps_the_layout_and_the_plugin_running(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("v1")

    def broken() -> ElgatoGrid:
        raise ConfigError("elgato.columns and elgato.rows go together")

    spec = PluginSpec(
        action_uuid=ACTION_UUID,
        grid=PHONE_PORTRAIT,
        key_count=15,
        key_size=72,
        layout=KeyLayout(exit_key=True),
        reload=GridReload(config_file, broken, interval=0.01),
    )
    apps: list[WatchedApp] = []

    def factory(url: str, **callbacks: Callable[..., None]) -> WatchedApp:
        apps.append(WatchedApp(url, **callbacks))
        return apps[0]

    task = asyncio.create_task(
        run_plugin(
            PluginArgs(1, "u", "register"),
            Config(),
            tmp_path / "no.sock",
            spec,
            app_factory=factory,
        )
    )
    for _ in range(300):
        if apps and any(m["event"] == "setImage" for m in apps[0].sent):
            break
        await asyncio.sleep(0.01)
    config_file.write_text("a half-written file")
    for _ in range(300):
        if "could not reload" in caplog.text:
            break
        await asyncio.sleep(0.01)
    assert "keeping the current layout" in caplog.text
    assert not task.done()  # still serving
    apps[0].release.set()
    await asyncio.wait_for(task, 5)
