from __future__ import annotations

from pathlib import Path

from streamdock_plugin.runner import default_log_file


def test_macos_logs_go_to_library_logs() -> None:
    path = default_log_file("plugin.log", platform="darwin", env={}, home=Path("/Users/me"))
    assert path == Path("/Users/me/Library/Logs/herdr-dock/plugin.log")


def test_linux_logs_follow_xdg_state_home() -> None:
    home = Path("/home/me")
    assert default_log_file("p.log", platform="linux", env={}, home=home) == Path(
        "/home/me/.local/state/herdr-dock/p.log"
    )
    assert default_log_file(
        "p.log", platform="linux", env={"XDG_STATE_HOME": "/s"}, home=home
    ) == Path("/s/herdr-dock/p.log")
