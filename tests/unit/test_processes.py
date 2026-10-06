from __future__ import annotations

from herdr_core.processes import Process, ancestors


def tree() -> dict[int, Process]:
    return {
        10: Process(10, 1, ("/Applications/Term.app/Contents/MacOS/term",)),
        20: Process(20, 10, ("-zsh",)),
        30: Process(30, 20, ("herdr",)),
        99: Process(99, 98, ("orphan",)),  # its parent isn't in the table
    }


def test_ancestors_walk_from_the_process_up_to_the_root() -> None:
    assert [p.pid for p in ancestors(30, tree())] == [30, 20, 10]


def test_a_missing_parent_ends_the_walk() -> None:
    assert [p.pid for p in ancestors(99, tree())] == [99]


def test_an_unknown_pid_yields_nothing() -> None:
    assert list(ancestors(12345, tree())) == []


def test_a_parent_loop_cannot_hang_the_walk() -> None:
    looped = {2: Process(2, 3, ("a",)), 3: Process(3, 2, ("b",))}
    assert [p.pid for p in ancestors(2, looped)] == [2, 3]
