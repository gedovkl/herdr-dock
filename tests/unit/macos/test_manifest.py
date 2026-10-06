from __future__ import annotations

import json
from pathlib import Path

from macos.plugin import ACTION_UUID

PLUGIN = Path(__file__).resolve().parents[3] / "macos" / "com.herdr.dock.sdPlugin"
MANIFEST = json.loads((PLUGIN / "manifest.json").read_text())


def test_the_manifest_declares_the_action_the_plugin_handles() -> None:
    assert [action["UUID"] for action in MANIFEST["Actions"]] == [ACTION_UUID]


def test_every_image_the_manifest_names_exists() -> None:
    paths = {MANIFEST["Icon"], MANIFEST["CategoryIcon"]}
    for action in MANIFEST["Actions"]:
        paths.add(action["Icon"])
        paths.update(state["Image"] for state in action["States"])
    assert all((PLUGIN / path).is_file() for path in paths), paths


def test_the_entry_point_name_matches_what_the_build_produces() -> None:
    assert MANIFEST["CodePathMac"] == "herdr-dock-plugin"
    spec = (PLUGIN.parent / "plugin.spec").read_text()
    assert 'name="herdr-dock-plugin"' in spec


def test_the_action_only_targets_keys() -> None:
    """The M18 has no dials; a Knob controller would offer the action where it can't work."""
    assert all(action["Controllers"] == ["Keypad"] for action in MANIFEST["Actions"])


def test_only_macos_is_listed() -> None:
    assert [os["Platform"] for os in MANIFEST["OS"]] == ["mac"]
