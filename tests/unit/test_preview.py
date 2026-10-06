from pathlib import Path

from PIL import Image

from herdr_core.preview import SAMPLES, main


def test_writes_every_frame_and_a_sheet(tmp_path: Path, capsys: object) -> None:
    assert main(["--out", str(tmp_path)]) == 0
    files = sorted(p.name for p in tmp_path.glob("*.png"))
    assert "sheet.png" in files
    assert "agent-blocked-blink0.png" in files and "agent-blocked-blink1.png" in files
    assert "agent-working-spin3.png" in files
    assert "empty.png" in files
    sheet = Image.open(tmp_path / "sheet.png")
    assert sheet.height >= len(SAMPLES) * 64 * 3


def test_custom_size(tmp_path: Path) -> None:
    assert main(["--out", str(tmp_path), "--size", "96"]) == 0
    assert Image.open(tmp_path / "empty.png").size == (96, 96)


def test_invalid_size(tmp_path: Path) -> None:
    assert main(["--out", str(tmp_path), "--size", "8"]) == 2
