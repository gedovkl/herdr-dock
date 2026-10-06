from pathlib import Path

from herdr_core.config import load_config
from linux.config import load_linux_config

EXAMPLE = Path(__file__).parents[2] / "config.example.toml"


def test_example_config_is_valid_and_matches_defaults() -> None:
    config = load_config(EXAMPLE)
    linux = load_linux_config(EXAMPLE)
    assert config.raise_window.linux == "herdr-window"
    assert [k.label or k.widget for k in linux.home] == [
        "herdr",
        "Browser",
        "Merge",
        "Zed",
        "clock",
        "weather",
    ]
    assert linux.home[0].herdr
    assert linux.home[3].focus == r"^dev\.zed\.Zed$"
    assert linux.buttons == {"left": "herdr", "middle": "none", "right": "page"}
