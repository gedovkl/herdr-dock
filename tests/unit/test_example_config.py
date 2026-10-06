from pathlib import Path

from herdr_core.config import load_config
from linux.config import load_linux_config

EXAMPLE = Path(__file__).parents[2] / "config.example.toml"


def test_example_config_is_valid_and_matches_defaults() -> None:
    config = load_config(EXAMPLE)
    linux = load_linux_config(EXAMPLE)
    assert config.raise_window.linux == "herdr-window"
    assert linux.home[0].herdr
    assert linux.buttons == {"left": "herdr", "middle": "none", "right": "page"}
