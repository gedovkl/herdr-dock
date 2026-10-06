"""KeySurface for the StreamDock app: draws a key by sending `setImage` to its context."""

from __future__ import annotations

from macos.protocol import set_image_message
from macos.transport import PluginTransport


class StreamDockSurface:
    """Maps physical key indexes to the app's per-key contexts.

    The app only lets us draw on keys that hold one of our actions, so a key with no context
    (such as the folder's own back key) is skipped instead of treated as an error.
    """

    def __init__(self, transport: PluginTransport) -> None:
        self._transport = transport
        self._by_key: dict[int, str] = {}
        self._by_context: dict[str, int] = {}

    @property
    def count(self) -> int:
        return len(self._by_context)

    def key_of(self, context: str) -> int | None:
        return self._by_context.get(context)

    def attach(self, context: str, key: int) -> None:
        """A context now sits on `key` (it appeared, or was dragged somewhere else)."""
        self.detach(context)
        stale = self._by_key.get(key)
        if stale is not None:
            del self._by_context[stale]
        self._by_key[key] = context
        self._by_context[context] = key

    def detach(self, context: str) -> None:
        key = self._by_context.pop(context, None)
        if key is not None and self._by_key.get(key) == context:
            del self._by_key[key]

    async def show(self, key: int, png: bytes) -> None:
        context = self._by_key.get(key)
        if context is None:
            return
        self._transport.send(set_image_message(context, png))
