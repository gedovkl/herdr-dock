from __future__ import annotations

from pathlib import Path

from macos.herdr_path import find_herdr, herdr_status_reader

HOME = Path("/home/u")


def make_binary(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    binary = directory / "herdr"
    binary.write_text("#!/bin/sh\necho 'socket: /tmp/x.sock'\n")
    binary.chmod(0o755)
    return binary


def test_finds_herdr_on_the_given_path(tmp_path: Path) -> None:
    binary = make_binary(tmp_path / "bin")
    assert find_herdr(str(tmp_path / "bin"), tmp_path) == binary


def test_falls_back_to_the_usual_install_dirs(tmp_path: Path) -> None:
    """Plugins get a minimal PATH without ~/.local/bin."""
    binary = make_binary(tmp_path / ".local" / "bin")
    assert find_herdr("/usr/bin:/bin", tmp_path) == binary


def test_the_apps_semicolon_path_entry_is_harmless(tmp_path: Path) -> None:
    binary = make_binary(tmp_path / ".local" / "bin")
    app_path = "/usr/bin:/bin:/usr/sbin:/sbin;/Applications/VSD Craft.app/Contents/MacOS"
    assert find_herdr(app_path, tmp_path) == binary


def test_returns_none_when_not_installed(tmp_path: Path) -> None:
    assert find_herdr("/usr/bin:/bin", tmp_path) is None


def test_ignores_a_directory_named_herdr(tmp_path: Path) -> None:
    (tmp_path / "bin" / "herdr").mkdir(parents=True)
    assert find_herdr(str(tmp_path / "bin"), tmp_path) is None


def test_status_reader_runs_the_found_binary(tmp_path: Path) -> None:
    make_binary(tmp_path / ".local" / "bin")
    read = herdr_status_reader("/usr/bin:/bin", tmp_path)
    assert read() == "socket: /tmp/x.sock\n"


def test_status_reader_without_herdr_returns_none(tmp_path: Path) -> None:
    assert herdr_status_reader("/usr/bin:/bin", tmp_path)() is None
