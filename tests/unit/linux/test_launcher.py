import subprocess
from pathlib import Path
from typing import Any

from linux.launcher import ShellLauncher


class Spawner:
    def __init__(self, error: OSError | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.error = error

    def __call__(self, command: str, **kwargs: Any) -> None:
        self.calls.append((command, kwargs))
        if self.error:
            raise self.error


def test_run_detaches() -> None:
    spawn = Spawner()
    ShellLauncher(spawn=spawn).run("make build")
    command, kwargs = spawn.calls[0]
    assert command == "make build"
    assert kwargs["shell"] and kwargs["start_new_session"]
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["cwd"] == Path.home()  # not the daemon's SDK work directory


def test_app_uses_quoted_launcher_template() -> None:
    spawn = Spawner()
    launcher = ShellLauncher("gtk-launch {app}", spawn=spawn)
    launcher.app("my app; rm -rf /")
    assert spawn.calls[0][0] == "gtk-launch 'my app; rm -rf /'"


def test_spawn_errors_are_logged(caplog: Any) -> None:
    ShellLauncher(spawn=Spawner(FileNotFoundError("sh"))).run("x")
    assert "could not start" in caplog.text
