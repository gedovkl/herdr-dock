from __future__ import annotations

import logging
from pathlib import Path

from herdr_core.config import Config
from herdr_core.faces import KeyLayout
from herdr_core.models import AgentStatus
from herdr_core.raise_window import NullRaiser
from herdr_core.wiring import build_herdr_stack, configure_logging, start_herdr, stop_herdr
from tests.fakes.surface import FakeSurface


def test_stack_pieces_are_wired_together(tmp_path: Path) -> None:
    surface = FakeSurface()
    layout = KeyLayout(exit_key=True)
    stack = build_herdr_stack(
        Config(), surface, NullRaiser(), tmp_path / "h.sock", layout=layout, key_count=15
    )
    # The session's capacity leaves key 0 for Exit: 14 session keys.
    assert len(stack.session.view.page.agents) == 14
    # A session view reaches the presenter, which draws on the surface.
    stack.presenter.update(stack.session.view)
    assert stack.presenter.faces


def test_configured_colours_reach_the_renderer(tmp_path: Path) -> None:
    config = Config(colors={AgentStatus.BLOCKED: "#123456"})
    default = build_herdr_stack(
        Config(), FakeSurface(), NullRaiser(), tmp_path / "a", layout=KeyLayout(), key_count=15
    )
    custom = build_herdr_stack(
        config, FakeSurface(), NullRaiser(), tmp_path / "a", layout=KeyLayout(), key_count=15
    )
    assert custom.renderer is not default.renderer
    assert custom.renderer._palette != default.renderer._palette


def test_configure_logging_levels_and_file(tmp_path: Path) -> None:
    root = logging.getLogger()
    before = list(root.handlers), root.level
    try:
        log_file = tmp_path / "logs" / "x.log"
        configure_logging(verbose=True, log_file=log_file)
        assert root.level == logging.DEBUG
        logging.getLogger("t").info("hello")
        for handler in root.handlers:
            handler.flush()
        assert "hello" in log_file.read_text()
        assert logging.getLogger("PIL").level == logging.INFO
        configure_logging(verbose=False)
        assert root.level == logging.INFO
    finally:
        for handler in list(root.handlers):
            if handler not in before[0]:
                root.removeHandler(handler)
                handler.close()
        root.setLevel(before[1])


class Recorder:
    def __init__(self, name: str, calls: list[str]) -> None:
        self._name, self._calls = name, calls

    def invalidate(self) -> None:
        self._calls.append(f"{self._name}.invalidate")

    async def start(self) -> None:
        self._calls.append(f"{self._name}.start")

    async def stop(self) -> None:
        self._calls.append(f"{self._name}.stop")


async def test_start_redraws_then_starts_presenter_then_session() -> None:
    calls: list[str] = []
    await start_herdr(Recorder("presenter", calls), Recorder("session", calls))
    assert calls == ["presenter.invalidate", "presenter.start", "session.start"]


async def test_stop_halts_the_presenter_before_the_session() -> None:
    calls: list[str] = []
    await stop_herdr(Recorder("presenter", calls), Recorder("session", calls))
    assert calls == ["presenter.stop", "session.stop"]
