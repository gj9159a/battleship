import pytest

from app.engine.board import Board
from app.engine.types import Placement


def test_fire_miss_hit_sunk_sequence() -> None:
    board = Board(size=5)
    board.place_ship(Placement(1, 1, 2, "H"))

    miss = board.fire((0, 0))
    hit = board.fire((1, 1))
    sunk = board.fire((1, 2))

    assert miss.outcome == "miss"
    assert hit.outcome == "hit"
    assert sunk.outcome == "sunk"
    assert board.all_sunk is True


def test_repeat_shot_raises() -> None:
    board = Board(size=5)
    board.place_ship(Placement(1, 1, 1, "H"))
    board.fire((0, 0))

    with pytest.raises(ValueError, match="already made"):
        board.fire((0, 0))


def test_out_of_bounds_shot_raises() -> None:
    board = Board(size=5)
    with pytest.raises(ValueError, match="out of bounds"):
        board.fire((5, 5))
