from pathlib import Path

import pytest

from herdr_core.socket_path import read_herdr_status, resolve_socket_path

HOME = Path("/home/u")
STATUS = "status: running\nversion: 0.8.2\nsocket: /run/herdr/x.sock\n"


def never() -> str | None:
    raise AssertionError("herdr status should not be consulted")


def test_explicit_wins() -> None:
    env = {"HERDR_SOCKET": "/env.sock"}
    assert resolve_socket_path("~/a.sock", env, HOME, never) == Path.home() / "a.sock"


def test_env_before_status() -> None:
    assert resolve_socket_path("", {"HERDR_SOCKET": "/env.sock"}, HOME, never) == Path("/env.sock")


def test_status_output() -> None:
    assert resolve_socket_path("", {}, HOME, lambda: STATUS) == Path("/run/herdr/x.sock")


def test_default_when_status_has_no_socket_or_fails() -> None:
    default = HOME / ".config/herdr/herdr.sock"
    assert resolve_socket_path("", {}, HOME, lambda: "status: stopped\nsocket:\n") == default
    assert resolve_socket_path("", {}, HOME, lambda: None) == default


def test_read_herdr_status_handles_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/nonexistent")
    assert read_herdr_status() is None


def test_read_herdr_status_returns_stdout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = tmp_path / "herdr"
    fake.write_text("#!/bin/sh\necho 'socket: /tmp/x.sock'\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert read_herdr_status() == "socket: /tmp/x.sock\n"


def test_read_herdr_status_runs_the_given_binary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = tmp_path / "my-herdr"
    fake.write_text('#!/bin/sh\necho "socket: /tmp/$1.sock"\n')
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", "/nonexistent")
    assert read_herdr_status(str(fake)) == "socket: /tmp/status.sock\n"
