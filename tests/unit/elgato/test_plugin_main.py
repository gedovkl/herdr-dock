from __future__ import annotations

import json
from pathlib import Path

import pytest

from elgato.grid import ElgatoGrid
from elgato.plugin_main import make_spec
from streamdock_plugin.runner import PluginArgs


def args(devices: list[tuple[int, int]]) -> PluginArgs:
    info = json.dumps(
        {
            "devices": [
                {"id": str(i), "size": {"columns": c, "rows": r}}
                for i, (c, r) in enumerate(devices)
            ]
        }
    )
    return PluginArgs(1, "uuid", "registerPlugin", info)


@pytest.fixture(autouse=True)
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return tmp_path


def test_the_spec_follows_the_first_device_in_the_launch_info() -> None:
    spec = make_spec(args([(8, 4)]))
    assert spec.key_count == 32
    assert spec.key_size == 144
    assert spec.layout.exit_key  # a folder's back key takes the top-left key by default
    assert spec.corner_radius == 0.15
    assert isinstance(spec.grid, ElgatoGrid)
    assert spec.grid.key_index(0, 0) == 0
    assert spec.grid.key_index(7, 3) == 31


def test_outside_a_folder_every_key_shows_an_agent(home: Path) -> None:
    config_dir = home / ".config" / "herdr-dock"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text("[elgato]\nfolder = false\ncorner_radius = 0\n")
    spec = make_spec(args([(5, 3)]))
    assert not spec.layout.exit_key
    assert spec.corner_radius == 0
    assert isinstance(spec.grid, ElgatoGrid)
    assert spec.grid.key_index(0, 0) == 0


def test_portrait_turns_the_grid_for_a_phone(home: Path) -> None:
    config_dir = home / ".config" / "herdr-dock"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text("[elgato]\nportrait = true\n")
    spec = make_spec(args([(5, 3)]))
    assert isinstance(spec.grid, ElgatoGrid)
    assert spec.grid.key_index(0, 0) == 0  # the back key: top-right on the phone
    assert spec.grid.key_index(0, 2) == 1  # top-left on the phone


def test_the_config_overrides_the_launch_info(home: Path) -> None:
    config_dir = home / ".config" / "herdr-dock"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text("[elgato]\ncolumns = 3\nrows = 2\nkey_size = 72\n")
    spec = make_spec(args([(8, 4)]))
    assert (spec.key_count, spec.key_size) == (6, 72)


def test_a_broken_config_falls_back_to_the_defaults(
    home: Path, caplog: pytest.LogCaptureFixture
) -> None:
    config_dir = home / ".config" / "herdr-dock"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text("[elgato]\ncolumns = 3\n")
    spec = make_spec(args([(5, 3)]))
    assert spec.key_count == 15
    assert "using the defaults" in caplog.text


def test_with_no_devices_anywhere_it_assumes_5x3() -> None:
    assert make_spec(args([])).key_count == 15


def test_mirror_reverses_the_rows_of_a_display_that_runs_right_to_left(home: Path) -> None:
    config_dir = home / ".config" / "herdr-dock"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text("[elgato]\nmirror = true\n")
    spec = make_spec(args([(5, 3)]))
    assert isinstance(spec.grid, ElgatoGrid)
    assert spec.grid.key_index(0, 0) == 0  # the back key, top-right
    assert spec.grid.key_index(4, 0) == 1  # the first agent key, top-left
