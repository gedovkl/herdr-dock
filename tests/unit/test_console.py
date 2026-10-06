from __future__ import annotations

import asyncio
import io
from pathlib import Path

import pytest

from herdr_core.client import HerdrSocketClient
from herdr_core.config import Config
from herdr_core.console import follow, format_view, main
from herdr_core.models import Agent, AgentStatus
from herdr_core.paging import paginate
from herdr_core.session import SessionView
from tests.fakes.herdr_server import FakeHerdrServer


def agent(n: int, status: AgentStatus = AgentStatus.IDLE, focused: bool = False) -> Agent:
    return Agent(f"w{n}:p1", f"w{n}", f"w{n}:t1", "claude", status, cwd=f"/p/{n}", focused=focused)


def view_of(slots: list[Agent | None], capacity: int, connected: bool = True) -> SessionView:
    agents = [a for a in slots if a]
    return SessionView(
        connected, paginate(slots, capacity, 0), len(agents), frozenset(a.status for a in agents)
    )


def test_format_view_lists_agents_with_herdr_symbols() -> None:
    slots = [agent(1, AgentStatus.BLOCKED, focused=True), None, agent(3)]
    text = format_view(view_of(slots, 5), "cwd")
    lines = text.splitlines()
    assert lines[0] == "herdr: connected · 2 agents · page 1/1"
    assert lines[1].startswith("  1* ×  claude     blocked  1")
    assert lines[2] == "  2  -"
    assert lines[3].startswith("  3  ○  claude     idle")
    assert len(lines) == 4  # trailing empty keys are not printed


def test_format_view_pager_line() -> None:
    slots = [agent(1), agent(2, AgentStatus.DONE), agent(3, AgentStatus.BLOCKED)]
    lines = format_view(view_of(slots, 2), "cwd").splitlines()
    assert lines[0].endswith("page 1/3")
    assert lines[-1] == "  2  ▶ next page   off-page: ×✓"


def test_format_view_offline_and_empty() -> None:
    assert format_view(view_of([], 3, connected=False), "cwd") == (
        "herdr: offline · 0 agents · page 1/1"
    )


def test_format_view_pager_without_offpage_agents() -> None:
    view = SessionView(True, paginate([agent(1), agent(2), None, None], 3, 0), 2, frozenset())
    assert format_view(view, "cwd").splitlines()[-1].endswith("off-page: -")


def run_main(args: list[str]) -> tuple[int, str]:
    out = io.StringIO()
    code = main(args, out=out, env={}, read_status=lambda: None)
    return code, out.getvalue()


async def test_main_once(herdr_server: FakeHerdrServer) -> None:
    herdr_server.add_agent("w1:p1", "working")
    code, output = await asyncio.to_thread(run_main, ["--socket", str(herdr_server.path), "--once"])
    assert code == 0
    assert "w1:p1" in output and "◐" in output


def test_main_once_unreachable(short_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _ = run_main(["--socket", str(short_dir / "nope.sock"), "--once"])
    assert code == 1
    assert "cannot connect" in capsys.readouterr().err


def test_main_rejects_bad_capacity(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_main(["--capacity", "1", "--once"])[0] == 2
    assert "--capacity" in capsys.readouterr().err


def test_main_rejects_bad_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "c.toml"
    config.write_text('label = "nope"')
    assert run_main(["--config", str(config), "--once"])[0] == 2
    assert "label must be" in capsys.readouterr().err


def test_main_follow_exits_cleanly_on_ctrl_c(
    short_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupted(coro: object) -> int:
        coro.close()  # type: ignore[attr-defined]
        raise KeyboardInterrupt

    monkeypatch.setattr("herdr_core.console.asyncio.run", interrupted)
    assert run_main(["--socket", str(short_dir / "x.sock"), "-v"])[0] == 0


async def test_follow_prints_each_change(herdr_server: FakeHerdrServer) -> None:
    herdr_server.add_agent("w1:p1", "idle")
    out = io.StringIO()
    stop = asyncio.Event()
    task = asyncio.create_task(
        follow(HerdrSocketClient(herdr_server.path), Config(), 3, out, stop.wait())
    )

    async def wait_for_text(text: str) -> None:
        while text not in out.getvalue():
            await asyncio.sleep(0)

    await asyncio.wait_for(wait_for_text("herdr: connected"), 2.0)
    await herdr_server.set_status("w1:p1", "blocked")
    await asyncio.wait_for(wait_for_text("blocked"), 2.0)
    stop.set()
    assert await task == 0
    assert out.getvalue().rstrip().endswith("herdr: offline · 0 agents · page 1/1")


class Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


async def test_follow_clears_screen_on_tty(short_dir: Path) -> None:
    out = Tty()
    done = asyncio.get_running_loop().create_future()
    done.set_result(None)
    await follow(HerdrSocketClient(short_dir / "x.sock"), Config(), 3, out, done)
    assert out.getvalue().startswith("\033[H\033[2J")
