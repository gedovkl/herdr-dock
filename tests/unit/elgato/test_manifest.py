from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image

from elgato.grid import ACTION_UUID

PLUGIN = Path(__file__).resolve().parents[3] / "elgato" / "com.herdr.dock.sdPlugin"
MANIFEST = json.loads((PLUGIN / "manifest.json").read_text())
REQUIRED = {
    "Actions", "Author", "CodePath", "Description", "Icon", "Name", "OS",
    "SDKVersion", "Software", "UUID", "Version",
}  # fmt: skip


def test_every_required_field_is_present() -> None:
    assert set(MANIFEST) >= REQUIRED


def test_versions_have_the_formats_the_app_wants() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+\.\d+", MANIFEST["Version"])
    assert MANIFEST["SDKVersion"] in (2, 3)
    assert re.fullmatch(r"\d+\.\d+", MANIFEST["Software"]["MinimumVersion"])


def test_the_action_belongs_to_the_plugin() -> None:
    assert [a["UUID"] for a in MANIFEST["Actions"]] == [ACTION_UUID]
    assert ACTION_UUID.startswith(MANIFEST["UUID"] + ".")
    assert re.fullmatch(r"[a-z0-9.-]+", ACTION_UUID)


def test_the_action_only_targets_keys() -> None:
    assert all(a["Controllers"] == ["Keypad"] for a in MANIFEST["Actions"])


def test_the_entry_point_name_matches_what_the_build_produces() -> None:
    assert MANIFEST["CodePath"] == MANIFEST["CodePathMac"] == "herdr-dock-plugin"
    assert 'name="herdr-dock-plugin"' in (PLUGIN.parent / "plugin.spec").read_text()


def test_it_is_a_mac_plugin_for_now() -> None:
    assert [os["Platform"] for os in MANIFEST["OS"]] == ["mac"]


def image_names() -> dict[str, int]:
    """Extension-less image path -> its 1x size in pixels, per Elgato's manifest reference."""
    sizes = {MANIFEST["Icon"]: 256, MANIFEST["CategoryIcon"]: 28}
    for action in MANIFEST["Actions"]:
        sizes[action["Icon"]] = 20
        sizes.update({state["Image"]: 72 for state in action["States"]})
    return sizes


def test_every_image_exists_at_1x_and_2x_with_the_right_size() -> None:
    for name, size in image_names().items():
        for suffix, scale in (("", 1), ("@2x", 2)):
            image = Image.open(PLUGIN / f"{name}{suffix}.png")
            assert image.size == (size * scale, size * scale), (name, suffix)


def test_the_list_icons_are_white_on_transparent() -> None:
    for name in (MANIFEST["CategoryIcon"], MANIFEST["Actions"][0]["Icon"]):
        image = Image.open(PLUGIN / f"{name}.png").convert("RGBA")
        assert image.getchannel("A").getbbox() is not None, name  # not an empty image
        for x in range(image.width):
            for y in range(image.height):
                red, green, blue, alpha = image.getpixel((x, y))  # type: ignore[misc]
                assert alpha == 0 or (red, green, blue) == (255, 255, 255), (name, x, y)
