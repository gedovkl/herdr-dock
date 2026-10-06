from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from herdr_core.models import Agent, AgentStatus
from linux.hyprland import (
    HerdrWindowRaiser,
    Hyprland,
    Process,
    WindowFocuser,
    herdr_clients,
    read_processes,
    run_exec,
    window_for,
    window_matching,
)

AGENT = Agent("w1:p1", "w1", "w1:t1", "claude", AgentStatus.IDLE)

PROCESSES = {
    1: Process(1, 0, ("systemd",)),
    100: Process(100, 1, ("Hyprland",)),
    200: Process(200, 100, ("foot",)),
    210: Process(210, 200, ("bash",)),
    220: Process(220, 210, ("herdr",)),
    230: Process(230, 220, ("/usr/bin/herdr", "server")),
    240: Process(240, 210, ("herdr", "agent", "list")),
    300: Process(300, 100, ("kitty",)),
    310: Process(310, 300, ("herdr", "--session", "work")),
    320: Process(320, 1, ("herdr", "session", "attach", "x")),
}
WINDOWS = [
    {"pid": 200, "address": "0xfoot", "focusHistoryID": 3},
    {"pid": 300, "address": "0xkitty", "focusHistoryID": 1},
    {"pid": 400, "address": "0xother", "focusHistoryID": 0},
    {"address": "0xnopid"},
]


def test_herdr_clients_skip_server_and_cli_calls() -> None:
    assert [p.pid for p in herdr_clients(PROCESSES.values())] == [220, 310, 320]


def test_window_for_prefers_most_recently_focused() -> None:
    clients = herdr_clients(PROCESSES.values())
    assert window_for(clients, PROCESSES, WINDOWS) == "0xkitty"
    only_foot = [p for p in clients if p.pid == 220]
    assert window_for(only_foot, PROCESSES, WINDOWS) == "0xfoot"
    assert window_for(only_foot, PROCESSES, []) is None
    orphan = [Process(999, 998, ("herdr",))]
    assert window_for(orphan, PROCESSES, WINDOWS) is None
    no_history = [{"pid": 200, "address": "0xfoot"}]
    assert window_for(only_foot, PROCESSES, no_history) == "0xfoot"
    bad_address = [{"pid": 200, "address": 5}]
    assert window_for(only_foot, PROCESSES, bad_address) is None


def test_read_processes(tmp_path: Path) -> None:
    for pid, ppid, comm, argv in [
        (5, 1, "herdr", b"herdr\0"),
        (6, 5, "weird) name", b"x\0y\0"),
    ]:
        (tmp_path / str(pid)).mkdir()
        (tmp_path / str(pid) / "stat").write_text(f"{pid} ({comm}) S {ppid} 1 1")
        (tmp_path / str(pid) / "cmdline").write_bytes(argv)
    (tmp_path / "7").mkdir()  # vanished process: no stat file
    (tmp_path / "self").mkdir()
    assert read_processes(tmp_path) == {
        5: Process(5, 1, ("herdr",)),
        6: Process(6, 5, ("x", "y")),
    }


@pytest.mark.skipif(not Path("/proc/self").exists(), reason="needs Linux /proc")
def test_read_real_proc_finds_this_process() -> None:
    import os

    assert os.getpid() in read_processes()


class Hyprctl:
    def __init__(self, clients: object = WINDOWS, focus: Sequence[tuple[int, str]] = ((0, "ok"),)):
        self.clients = clients
        self.focus = list(focus)
        self.calls: list[list[str]] = []

    async def __call__(self, argv: Sequence[str]) -> tuple[int, str]:
        self.calls.append(list(argv))
        if argv[1] == "clients":
            if isinstance(self.clients, tuple):
                return self.clients  # type: ignore[return-value]
            return 0, self.clients if isinstance(self.clients, str) else json.dumps(self.clients)
        return self.focus.pop(0)


async def test_focuses_window_with_lua_dispatcher() -> None:
    hyprctl = Hyprctl()
    await HerdrWindowRaiser(hyprctl, lambda: PROCESSES).raise_window(AGENT)
    focus = 'hl.dsp.focus({ window = "address:0xkitty" })'
    assert hyprctl.calls[-1] == ["hyprctl", "dispatch", focus]


async def test_falls_back_to_legacy_dispatcher(caplog: pytest.LogCaptureFixture) -> None:
    hyprctl = Hyprctl(focus=[(0, "error: lua"), (0, "ok")])
    await HerdrWindowRaiser(hyprctl, lambda: PROCESSES).raise_window(AGENT)
    assert hyprctl.calls[-1] == ["hyprctl", "dispatch", "focuswindow", "address:0xkitty"]
    failing = Hyprctl(focus=[(1, ""), (7, "")])
    await HerdrWindowRaiser(failing, lambda: PROCESSES).raise_window(AGENT)
    assert "could not focus window 0xkitty" in caplog.text


@pytest.mark.parametrize(
    ("clients", "processes", "message"),
    [
        ((1, ""), PROCESSES, "hyprctl clients failed"),
        ("not json", PROCESSES, "invalid JSON"),
        (WINDOWS, {}, "no window found"),
    ],
)
async def test_failures_are_logged(
    caplog: pytest.LogCaptureFixture, clients: object, processes: dict[int, Process], message: str
) -> None:
    caplog.set_level("INFO")
    hyprctl = Hyprctl(clients=clients)
    await HerdrWindowRaiser(hyprctl, lambda: processes).raise_window(AGENT)
    assert message in caplog.text
    assert all(call[1] == "clients" for call in hyprctl.calls)


async def test_run_exec() -> None:
    assert await run_exec(["sh", "-c", "echo hi; exit 3"]) == (3, "hi\n")
    assert await run_exec(["true"]) == (0, "")
    assert await run_exec(["sleep", "5"], timeout=0.05) == (-1, "")


CLASSED = [
    {"class": "chrome-omarchy.org__manual_-Default", "address": "0xweb", "focusHistoryID": 0},
    {"class": "chromium", "address": "0xold", "focusHistoryID": 5},
    {"class": "Chromium", "address": "0xnew", "focusHistoryID": 2},
    {"class": "foot", "address": "0xfoot", "focusHistoryID": 1},
]


def test_window_matching_is_anchored_regex_case_insensitive_most_recent() -> None:
    assert window_matching("^chromium$", CLASSED) == "0xnew"
    assert window_matching("chrom", CLASSED) == "0xweb"
    assert window_matching("^firefox$", CLASSED) is None
    assert window_matching("x", [{"class": "x", "address": 3}]) is None


async def test_window_focuser() -> None:
    hyprctl = Hyprctl(clients=CLASSED)
    assert await WindowFocuser(hyprctl).focus_matching("^chromium$")
    assert hyprctl.calls[-1][2] == 'hl.dsp.focus({ window = "address:0xnew" })'
    assert not await WindowFocuser(Hyprctl(clients=CLASSED)).focus_matching("^firefox$")
    assert not await WindowFocuser(Hyprctl(clients=(1, ""))).focus_matching("x")
    failing = Hyprctl(clients=CLASSED, focus=[(1, ""), (1, "")])
    assert not await WindowFocuser(failing).focus_matching("foot")


async def test_windows_must_be_a_list() -> None:
    assert await Hyprland(Hyprctl(clients={"not": "a list"})).windows() is None


async def test_missing_binary_is_a_failure_not_an_exception() -> None:
    assert await run_exec(["definitely-not-installed-hyprctl"]) == (127, "")


async def test_without_hyprctl_focus_and_raise_degrade_quietly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "/nonexistent")
    assert not await WindowFocuser().focus_matching("^chromium$")
    await HerdrWindowRaiser(processes=lambda: PROCESSES).raise_window(AGENT)


def test_single_process_terminal_picks_its_most_recent_window() -> None:
    """foot --server / ghostty / kitty --single-instance own several windows from one PID."""
    windows = [
        {"pid": 200, "address": "0xfoot-old", "focusHistoryID": 7},
        {"pid": 200, "address": "0xfoot-recent", "focusHistoryID": 2},
    ]
    clients = [p for p in herdr_clients(PROCESSES.values()) if p.pid == 220]
    assert window_for(clients, PROCESSES, windows) == "0xfoot-recent"


def test_window_for_finds_a_window_owned_by_a_process_missing_from_the_table() -> None:
    """The refactor to a shared ancestry walk must keep matching unreadable parents."""
    client = Process(230, 220, ("herdr",))
    table = {230: client}  # 220, the terminal, wasn't readable
    windows = [{"pid": 220, "address": "0xterm", "focusHistoryID": 0}]
    assert window_for([client], table, windows) == "0xterm"
