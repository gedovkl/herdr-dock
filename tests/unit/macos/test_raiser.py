from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

import pytest

from herdr_core.config import RaiseConfig
from herdr_core.models import Agent, AgentStatus
from herdr_core.raise_window import CommandRaiser, NullRaiser
from macos.raiser import TerminalRaiser, app_bundle, macos_raiser, parse_ps, terminal_app

AGENT = Agent("w1:p1", "w1", "w1:t1", "claude", AgentStatus.IDLE, cwd="/p")

PS = """\
    1     0 /sbin/launchd
 1042     1 /Applications/WezTerm.app/Contents/MacOS/wezterm-gui
 1181  1042 -zsh
 7852  1181 herdr
 7891  7852 /Users/me/.local/bin/herdr server
 8000     1 /Applications/Other App.app/Contents/MacOS/other
 8100  8000 herdr --session work
"""


def test_parse_ps_reads_pid_parent_and_command() -> None:
    processes = parse_ps(PS)
    assert processes[7852].ppid == 1181
    assert processes[7891].argv == ("/Users/me/.local/bin/herdr", "server")
    assert processes[1042].argv[0].endswith("wezterm-gui")


def test_parse_ps_skips_garbage_lines() -> None:
    assert list(parse_ps("junk\n  12 x y\n\n  13     1 init\n")) == [13]


def test_app_bundle_from_an_executable_path() -> None:
    assert app_bundle("/Applications/WezTerm.app/Contents/MacOS/wezterm-gui") == Path(
        "/Applications/WezTerm.app"
    )
    assert app_bundle("/usr/bin/zsh") is None
    assert app_bundle("/Applications/Odd.app") is None  # not an executable inside a bundle


def test_the_terminal_is_the_app_above_the_herdr_client() -> None:
    processes = parse_ps(PS)
    clients = [processes[7852]]
    assert terminal_app(clients, processes) == Path("/Applications/WezTerm.app")


def test_paths_with_spaces_survive() -> None:
    processes = parse_ps(PS)
    assert terminal_app([processes[8100]], processes) == Path("/Applications/Other App.app")


def test_no_app_above_the_client_means_none() -> None:
    processes = parse_ps("  5     1 -zsh\n  6     5 herdr\n")
    assert terminal_app([processes[6]], processes) is None


class Runner:
    def __init__(self, ps: str = PS, open_code: int = 0) -> None:
        self.ps = ps
        self.open_code = open_code
        self.calls: list[list[str]] = []

    async def __call__(self, argv: Sequence[str]) -> tuple[int, str]:
        self.calls.append(list(argv))
        if argv[0] == "ps":
            return 0, self.ps
        return self.open_code, ""


async def test_raises_the_terminal_that_hosts_herdr() -> None:
    run = Runner()
    await TerminalRaiser(run).raise_window(AGENT)
    assert run.calls[-1] == ["open", "/Applications/WezTerm.app"]


async def test_the_server_alone_is_not_a_client() -> None:
    run = Runner("  1042     1 /Applications/T.app/Contents/MacOS/t\n  7891  1042 herdr server\n")
    await TerminalRaiser(run).raise_window(AGENT)
    assert [call[0] for call in run.calls] == ["ps"]  # nothing to raise


async def test_no_terminal_found_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    run = Runner("  5     1 -zsh\n  6     5 herdr\n")
    with caplog.at_level(logging.INFO):
        await TerminalRaiser(run).raise_window(AGENT)
    assert "no terminal app" in caplog.text
    assert [call[0] for call in run.calls] == ["ps"]


async def test_a_failing_open_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        await TerminalRaiser(Runner(open_code=1)).raise_window(AGENT)
    assert "open" in caplog.text


async def test_ps_failure_does_nothing() -> None:
    run = Runner(ps="")
    await TerminalRaiser(run).raise_window(AGENT)
    assert [call[0] for call in run.calls] == ["ps"]


def test_default_is_the_terminal_raiser() -> None:
    assert isinstance(macos_raiser(RaiseConfig()), TerminalRaiser)
    assert isinstance(macos_raiser(RaiseConfig(macos="herdr-window")), TerminalRaiser)


def test_a_command_or_disabled_overrides_it() -> None:
    assert isinstance(macos_raiser(RaiseConfig(macos="open -a Ghostty")), CommandRaiser)
    assert isinstance(macos_raiser(RaiseConfig(enabled=False)), NullRaiser)
