from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from herdr_core.config import Config
from macos.plugin import ACTION_UUID
from macos.plugin_main import PluginArgs, parse_args, run_plugin

ARGV = [
    "-port",
    "18618",
    "-pluginUUID",
    "UUID1",
    "-registerEvent",
    "registerPlugin",
    "-info",
    '{"application": {"version": "3.10"}}',
]


def test_parse_args_reads_the_apps_launch_arguments() -> None:
    assert parse_args(ARGV) == PluginArgs(18618, "UUID1", "registerPlugin")


def test_parse_args_rejects_missing_arguments() -> None:
    with pytest.raises(SystemExit):
        parse_args(["-port", "1"])


class BlockingApp:
    """A fake app that replays messages, then stays 'connected' until released."""

    def __init__(self, url: str, **callbacks: Callable[..., None]) -> None:
        self.callbacks = callbacks
        self.sent: list[dict[str, Any]] = []
        self.release = threading.Event()
        self.script = [
            {
                "event": "deviceDidConnect",
                "device": "m18",
                "deviceInfo": {"size": {"columns": 5, "rows": 3}},
            },
            {
                "event": "willAppear",
                "action": ACTION_UUID,
                "context": "c1",
                "device": "m18",
                "payload": {"coordinates": {"column": 1, "row": 2}},
            },
        ]

    def run_forever(self) -> None:
        self.callbacks["on_open"](self)
        for message in self.script:
            self.callbacks["on_message"](self, json.dumps(message))
        self.release.wait(5)
        self.callbacks["on_close"](self, 1000, "bye")

    def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    def close(self) -> None:
        self.release.set()


async def test_a_visible_key_gets_drawn_and_a_closed_link_ends_the_plugin(tmp_path: Path) -> None:
    apps: list[BlockingApp] = []

    def factory(url: str, **callbacks: Callable[..., None]) -> BlockingApp:
        apps.append(BlockingApp(url, **callbacks))
        return apps[0]

    task = asyncio.create_task(
        run_plugin(
            PluginArgs(18618, "UUID1", "registerPlugin"),
            Config(),
            tmp_path / "no-herdr.sock",  # herdr isn't running: keys show "offline"
            app_factory=factory,
        )
    )
    app: BlockingApp | None = None
    for _ in range(300):
        await asyncio.sleep(0.01)
        app = apps[0] if apps else None
        if app and any(m["event"] == "setImage" for m in app.sent):
            break
    assert app is not None
    drawn = [m for m in app.sent if m["event"] == "setImage"]
    assert drawn and drawn[0]["context"] == "c1"
    assert app.sent[0] == {"event": "registerPlugin", "uuid": "UUID1"}
    app.release.set()  # the StreamDock app quits
    await asyncio.wait_for(task, 5)


def _run_main(monkeypatch: pytest.MonkeyPatch, home: Path) -> dict[str, Any]:
    from macos import plugin_main

    seen: dict[str, Any] = {}

    async def fake_run(args: PluginArgs, config: Config, socket: Path, **_: Any) -> None:
        seen.update(args=args, config=config, socket=socket)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("HERDR_SOCKET", raising=False)
    monkeypatch.setattr(plugin_main, "run_plugin", fake_run)
    monkeypatch.setattr(plugin_main, "default_log_file", lambda: home / "plugin.log")
    # Reconfiguring root logging would remove pytest's capture handler.
    monkeypatch.setattr(plugin_main, "configure_logging", lambda **_: None)
    assert plugin_main.main(ARGV) == 0
    return seen


def test_main_uses_the_shared_config_and_socket(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / ".config" / "herdr-dock"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text('herdr_socket = "/tmp/custom.sock"\nlabel = "title"\n')
    seen = _run_main(monkeypatch, tmp_path)
    assert seen["args"].port == 18618
    assert seen["config"].label == "title"
    assert seen["socket"] == Path("/tmp/custom.sock")


def test_main_survives_a_broken_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    config_dir = tmp_path / ".config" / "herdr-dock"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text("this is = = not toml")
    seen = _run_main(monkeypatch, tmp_path)
    assert seen["config"] == Config()
    assert "using the defaults" in caplog.text


def test_main_sets_home_for_herdr_when_the_app_does_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """herdr finds ~/.config/herdr through $HOME and reports a temp-dir socket without it."""
    _run_main(monkeypatch, tmp_path)  # applies the common patches and runs main()
    monkeypatch.delenv("HOME")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    from macos import plugin_main

    plugin_main.main(ARGV)
    import os

    assert os.environ["HOME"] == str(tmp_path)
