"""The M18's grid as the VSD Craft app reports it."""

from __future__ import annotations

COLUMNS, ROWS = 5, 3
"""The M18's key grid. Other docks aren't supported."""
ACTION_UUID = "com.herdr.dock.agent"
"""The one action. Put it on keys 2-15 of a folder; the core decides what each key shows."""


class M18Grid:
    def rejects(self, size: tuple[int, int] | None) -> str | None:
        if size is not None and size != (COLUMNS, ROWS):
            return f"is {size[0]}x{size[1]}; only the 5x3 M18 works"
        return None

    def key_index(self, column: int, row: int) -> int | None:
        if not (0 <= column < COLUMNS and 0 <= row < ROWS):
            return None
        # The app numbers the M18's rows from the bottom: its folder back key (top-left) is stored
        # at column 0, row 2. Key indexes count from the top-left like everywhere else here.
        return (ROWS - 1 - row) * COLUMNS + column
