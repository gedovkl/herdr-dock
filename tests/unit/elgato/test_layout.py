"""How (column, row) from the app maps to our key indexes on the phone and on a deck."""

from __future__ import annotations

import pytest

from elgato.grid import ElgatoGrid

COORDS_5X3 = [(c, r) for r in range(3) for c in range(5)]


def indexes(grid: ElgatoGrid) -> list[int | None]:
    return [grid.key_index(c, r) for c, r in COORDS_5X3]


def test_a_plain_deck_counts_in_reading_order() -> None:
    assert indexes(ElgatoGrid(5, 3)) == list(range(15))


def test_a_folder_reserves_the_top_left_back_key_as_index_0() -> None:
    grid = ElgatoGrid(5, 3, back_key=True)
    assert grid.key_index(0, 0) == 0
    assert grid.key_index(1, 0) == 1  # the next key in reading order
    assert sorted(i for i in indexes(grid) if i is not None) == list(range(15))


def test_the_phone_is_the_5x3_grid_turned_clockwise() -> None:
    """The phone shows 3 columns x 5 rows; the back key (app 0,0) is on row 1, column 3."""
    grid = ElgatoGrid(5, 3, portrait=True)
    # Read the phone left to right, top to bottom: phone (row p, column q) is app (p, 2 - q).
    phone = [(p, 2 - q) for p in range(5) for q in range(3)]
    assert [grid.key_index(c, r) for c, r in phone] == list(range(15))


def test_the_phone_with_a_folder_back_key_first_then_reading_order() -> None:
    grid = ElgatoGrid(5, 3, portrait=True, back_key=True)
    assert grid.key_index(0, 0) == 0  # top-right on the phone
    # The first phone row reads: key 1, key 2, back key.
    assert [grid.key_index(0, 2), grid.key_index(0, 1)] == [1, 2]
    # The second phone row follows: app (1,2), (1,1), (1,0).
    assert [grid.key_index(1, 2), grid.key_index(1, 1), grid.key_index(1, 0)] == [3, 4, 5]
    assert sorted(i for i in indexes(grid) if i is not None) == list(range(15))


@pytest.mark.parametrize("portrait", [False, True])
@pytest.mark.parametrize("back_key", [False, True])
def test_off_grid_positions_have_no_key(portrait: bool, back_key: bool) -> None:
    grid = ElgatoGrid(5, 3, portrait=portrait, back_key=back_key)
    assert grid.key_index(5, 0) is None
    assert grid.key_index(0, 3) is None
    assert grid.key_index(-1, 0) is None


def test_a_mirrored_deck_reads_each_row_right_to_left() -> None:
    """Shown right to left, the app's column 4 is the leftmost key and column 0 the rightmost."""
    grid = ElgatoGrid(5, 3, mirror=True)
    assert [grid.key_index(c, 0) for c in (4, 3, 2, 1, 0)] == [0, 1, 2, 3, 4]
    assert [grid.key_index(c, 1) for c in (4, 3, 2, 1, 0)] == [5, 6, 7, 8, 9]


def test_a_mirrored_folder_keeps_the_back_key_first_and_fills_from_the_left() -> None:
    grid = ElgatoGrid(5, 3, mirror=True, back_key=True)
    assert grid.key_index(0, 0) == 0  # the back key, now top-right
    assert [grid.key_index(c, 0) for c in (4, 3, 2, 1)] == [1, 2, 3, 4]  # top row, left to right
    assert [grid.key_index(c, 1) for c in (4, 3, 2, 1, 0)] == [5, 6, 7, 8, 9]
    assert sorted(i for i in indexes(grid) if i is not None) == list(range(15))


def test_mirroring_applies_to_the_rows_of_a_portrait_phone_too() -> None:
    grid = ElgatoGrid(5, 3, portrait=True, mirror=True)
    # Unmirrored, the phone's first row reads app (0,2), (0,1), (0,0); mirrored it is reversed.
    assert [grid.key_index(0, r) for r in (0, 1, 2)] == [0, 1, 2]
