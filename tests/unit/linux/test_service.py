import shlex
from pathlib import Path

from linux.service import main, render_unit

TEMPLATE = (Path(__file__).parents[3] / "linux" / "herdr-dock.service").read_text()


def exec_start(unit: str) -> list[str]:
    line = next(row for row in unit.splitlines() if row.startswith("ExecStart="))
    return shlex.split(line.removeprefix("ExecStart="))


def test_plain_paths() -> None:
    unit = render_unit(TEMPLATE, Path("/home/u/herdr-dock"), Path("/home/u/herdr-dock/.venv"))
    assert exec_start(unit) == ["/home/u/herdr-dock/.venv/bin/python", "-m", "linux.daemon"]
    assert "WorkingDirectory=/home/u/herdr-dock\n" in unit
    assert "@PYTHON@" not in unit and "@ROOT@" not in unit


def test_spaces_ampersands_pipes_and_percent_survive() -> None:
    root = Path("/home/u/My Projects/a&b|c 100%/herdr-dock")
    unit = render_unit(TEMPLATE, root, root / ".venv")
    assert exec_start(unit)[0] == f"{root}/.venv/bin/python".replace("%", "%%")
    assert f"WorkingDirectory={str(root).replace('%', '%%')}\n" in unit


def test_cli_prints_the_unit(tmp_path: Path, capsys: object) -> None:
    template = tmp_path / "t.service"
    template.write_text(TEMPLATE)
    assert main([str(template), "/r", "/r/.venv"]) == 0
    assert "WorkingDirectory=/r" in capsys.readouterr().out  # type: ignore[attr-defined]
