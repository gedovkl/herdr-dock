"""How an app numbers its keys. The one place the StreamDock-style apps differ."""

from __future__ import annotations

from typing import Protocol


class Grid(Protocol):
    def rejects(self, size: tuple[int, int] | None) -> str | None:
        """Why a dock of this size (columns, rows; None if not announced yet) can't be driven."""
        ...

    def key_index(self, column: int, row: int) -> int | None:
        """Key index counted from the top-left, left to right; None if off the grid."""
        ...
