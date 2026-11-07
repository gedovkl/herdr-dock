from __future__ import annotations

from pathlib import Path

from streamdock_plugin.icons import ICON_FACES, main, write_icons
from streamdock_plugin.widget_keys import WIDGET_KINDS


def test_every_widget_kind_gets_a_png(tmp_path: Path) -> None:
    assert set(ICON_FACES) == set(WIDGET_KINDS)
    written = write_icons(tmp_path / "img", size=72)
    assert sorted(p.name for p in written) == sorted(f"widget-{k}.png" for k in WIDGET_KINDS)
    assert all(p.read_bytes().startswith(b"\x89PNG") for p in written)


def test_main(tmp_path: Path, capsys: object) -> None:
    assert main([str(tmp_path)]) == 0
    assert (tmp_path / "widget-clock.png").exists()
    assert main([]) == 2
