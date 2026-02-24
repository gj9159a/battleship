import pytest

from app.engine.board import build_board_from_placements
from app.engine.types import Placement
from app.rulesets.catalog import CLASSIC_V1


def _classic_valid_placements() -> list[Placement]:
    return [
        Placement(0, 0, 5, "H"),
        Placement(2, 0, 4, "H"),
        Placement(4, 0, 3, "H"),
        Placement(6, 0, 3, "H"),
        Placement(8, 0, 2, "H"),
    ]


def test_classic_ruleset_defaults() -> None:
    assert CLASSIC_V1.id == "classic_v1"
    assert CLASSIC_V1.board_size == 10
    assert CLASSIC_V1.fleet == (5, 4, 3, 3, 2)
    assert CLASSIC_V1.placement_no_touch is False
    assert CLASSIC_V1.extra_turn_on_hit is False


def test_build_board_accepts_valid_classic_fleet() -> None:
    board = build_board_from_placements(CLASSIC_V1, _classic_valid_placements())
    assert board.ships_alive == 5


def test_build_board_rejects_wrong_fleet() -> None:
    placements = _classic_valid_placements()[:-1]
    with pytest.raises(ValueError, match="Fleet mismatch"):
        build_board_from_placements(CLASSIC_V1, placements)


def test_build_board_accepts_touching_ships_for_classic() -> None:
    placements = [
        Placement(0, 0, 5, "H"),
        Placement(1, 0, 4, "H"),
        Placement(3, 0, 3, "H"),
        Placement(5, 0, 3, "H"),
        Placement(7, 0, 2, "H"),
    ]
    board = build_board_from_placements(CLASSIC_V1, placements)
    assert board.ships_alive == 5
