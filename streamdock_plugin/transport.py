"""The plugin's connection to the StreamDock app."""

from __future__ import annotations

from typing import Protocol


class PluginTransport(Protocol):
    def send(self, message: str) -> None:
        """Send one JSON message to the app; raises ConnectionError if the link is down."""
        ...
