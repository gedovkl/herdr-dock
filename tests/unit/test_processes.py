from __future__ import annotations

from herdr_core.processes import Process, ancestor_pids, ancestors


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


def test_ancestor_pids_include_a_parent_that_is_missing_from_the_table() -> None:
    """A window can belong to a process we couldn't read; its pid must still be offered."""
    assert list(ancestor_pids(99, tree())) == [99, 98]
    assert list(ancestor_pids(30, tree())) == [30, 20, 10]
    assert list(ancestor_pids(12345, tree())) == [12345]


def test_ancestor_pids_stop_at_init_and_loops() -> None:
    looped = {2: Process(2, 3, ("a",)), 3: Process(3, 2, ("b",))}
    assert list(ancestor_pids(2, looped)) == [2, 3]
    assert list(ancestor_pids(1, looped)) == []
