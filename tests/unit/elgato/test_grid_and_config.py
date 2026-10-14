from __future__ import annotations

import json
from pathlib import Path

import pytest

from elgato.config import ElgatoConfig, choose_size, devices_from_info, load_elgato_config
from elgato.grid import ElgatoGrid
from herdr_core.config import ConfigError


def test_rows_are_numbered_from_the_top_left() -> None:
    grid = ElgatoGrid(5, 3)
    assert grid.key_index(0, 0) == 0
    assert grid.key_index(4, 0) == 4
    assert grid.key_index(0, 1) == 5
    assert grid.key_index(4, 2) == 14


def test_off_grid_positions_have_no_key() -> None:
    grid = ElgatoGrid(3, 2)
    assert grid.key_index(3, 0) is None
    assert grid.key_index(0, 2) is None
    assert grid.key_index(-1, 0) is None


def test_a_dock_of_another_size_is_rejected_with_a_reason() -> None:
    grid = ElgatoGrid(5, 3)
    assert grid.rejects((5, 3)) is None
    assert grid.rejects(None) is None  # not announced yet
    reason = grid.rejects((8, 4))
    assert reason is not None and "8x4" in reason and "[elgato]" in reason


INFO = json.dumps(
    {
        "devices": [
            {"id": "A", "name": "Phone", "size": {"columns": 8, "rows": 4}, "type": 7},
            {"id": "B", "name": "XL", "size": {"columns": 5, "rows": 3}, "type": 0},
        ]
    }
)


def test_devices_come_from_the_launch_info() -> None:
    assert devices_from_info(INFO) == [(8, 4), (5, 3)]


@pytest.mark.parametrize(
    "info",
    ["", "not json", "[]", "{}", '{"devices": 3}', '{"devices": [1, {"size": {"columns": "x"}}]}'],
)
def test_a_surprising_launch_info_yields_no_devices(info: str) -> None:
    assert devices_from_info(info) == []


def test_the_size_comes_from_config_then_the_first_device_then_5x3() -> None:
    assert choose_size(ElgatoConfig(columns=3, rows=2), [(8, 4)]) == (3, 2)
    assert choose_size(ElgatoConfig(), [(8, 4), (5, 3)]) == (8, 4)
    assert choose_size(ElgatoConfig(), []) == (5, 3)


def test_a_device_with_fewer_than_two_keys_is_skipped() -> None:
    assert choose_size(ElgatoConfig(), [(1, 1), (3, 2)]) == (3, 2)


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_the_config_defaults_when_there_is_no_section(tmp_path: Path) -> None:
    assert load_elgato_config(write(tmp_path, 'label = "cwd"\n')) == ElgatoConfig()


def test_the_config_reads_the_elgato_section(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "[elgato]\ncolumns = 8\nrows = 4\nkey_size = 72\n"
        "corner_radius = 0.2\nportrait = true\nmirror = true\nfolder = false\n",
    )
    assert load_elgato_config(path) == ElgatoConfig(
        columns=8, rows=4, key_size=72, corner_radius=0.2, portrait=True, mirror=True, folder=False
    )


def test_the_defaults_suit_a_folder_with_rounded_keys() -> None:
    config = ElgatoConfig()
    assert (config.folder, config.portrait, config.mirror, config.corner_radius) == (
        True,
        False,
        False,
        0.15,
    )


@pytest.mark.parametrize(
    "section",
    [
        "columns = 8\n",  # rows missing
        "columns = 1\nrows = 1\n",  # too small
        "columns = 0\nrows = 3\n",
        'columns = "8"\nrows = 4\n',
        "key_size = 8\n",
        "key_size = true\n",
        "corner_radius = 0.9\n",
        "corner_radius = -1\n",
        'corner_radius = "round"\n',
        'portrait = "yes"\n',
        "folder = 1\n",
        "mirror = 2\n",
    ],
)
def test_a_bad_elgato_section_is_a_config_error(tmp_path: Path, section: str) -> None:
    with pytest.raises(ConfigError):
        load_elgato_config(write(tmp_path, f"[elgato]\n{section}"))


def test_a_missing_default_file_means_defaults(tmp_path: Path) -> None:
    assert load_elgato_config(tmp_path / "nope.toml", explicit=False) == ElgatoConfig()
