"""The Elgato app's key grid, as the plugin numbers it.

The app reports every key as a (column, row) of the dock's own landscape grid, counted from the
top-left. Our key indexes follow what the user sees: left to right, top to bottom. Stream Deck
Mobile in portrait shows that grid turned 90 degrees clockwise (5 x 3 becomes 3 columns x 5 rows),
and inside a folder the app keeps the top-left key (app column 0, row 0) as its back key.
"""

from __future__ import annotations

ACTION_UUID = "com.herdr.dock.agent"
"""The one action. Put it on keys of a page; the core decides what each key shows."""

Cell = tuple[int, int]


class ElgatoGrid:
    """A dock of `columns` x `rows` keys (the app's landscape size). One size per run.

    `portrait` numbers the keys as they look on a phone held upright. `back_key` makes index 0 the
    app's folder back key; the other keys follow in reading order. `mirror` is for a display that
    shows each row right to left: the rows are read in the order they appear.
    """

    def __init__(
        self,
        columns: int,
        rows: int,
        *,
        portrait: bool = False,
        mirror: bool = False,
        back_key: bool = False,
    ) -> None:
        self._columns = columns
        self._rows = rows
        order = [
            cell
            for display_row in self._display_rows(portrait)
            for cell in (reversed(display_row) if mirror else display_row)
        ]
        if back_key:
            order = [(0, 0), *(cell for cell in order if cell != (0, 0))]
        self._index = {cell: index for index, cell in enumerate(order)}

    def _display_rows(self, portrait: bool) -> list[list[Cell]]:
        """The rows as displayed (top to bottom), each left to right, as app (column, row)."""
        if not portrait:
            return [[(c, r) for c in range(self._columns)] for r in range(self._rows)]
        # Turned clockwise, the app's row r becomes the phone's column (rows - 1 - r) and the
        # app's column c becomes the phone's row c.
        return [
            [(c, self._rows - 1 - phone_column) for phone_column in range(self._rows)]
            for c in range(self._columns)
        ]

    def rejects(self, size: tuple[int, int] | None) -> str | None:
        if size is not None and size != (self._columns, self._rows):
            return (
                f"is {size[0]}x{size[1]}, but this plugin is set up for "
                f"{self._columns}x{self._rows}; set columns and rows in [elgato] to change it"
            )
        return None

    def key_index(self, column: int, row: int) -> int | None:
        return self._index.get((column, row))
