from pathlib import Path

UNIT = Path(__file__).parents[3] / "linux" / "herdr-dock.service"


def test_unit_runs_the_daemon_from_the_venv_inside_the_graphical_session() -> None:
    text = UNIT.read_text()
    assert "ExecStart=@VENV@/bin/python -m linux.daemon" in text
    assert "WorkingDirectory=@ROOT@" in text
    assert "PartOf=graphical-session.target" in text
    assert "WantedBy=graphical-session.target" in text
    assert "Restart=on-failure" in text
