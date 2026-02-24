import pytest

from app.engine.board import build_board_from_placements
from app.engine.types import Placement
from app.rulesets.catalog import CLASSIC_V1


def _classic_valid_placements() -> list[Placement]:
    return [
        Placement(0, 0, 4, "H"),
        Placement(2, 0, 3, "H"),
        Placement(4, 0, 3, "H"),
        Placement(6, 0, 2, "H"),
        Placement(8, 0, 2, "H"),
        Placement(0, 5, 2, "V"),
        Placement(3, 5, 1, "H"),
        Placement(5, 5, 1, "H"),
        Placement(7, 5, 1, "H"),
        Placement(9, 5, 1, "H"),
    ]


def test_classic_ruleset_defaults() -> None:
    assert CLASSIC_V1.id == "classic_v1"
    assert CLASSIC_V1.board_size == 10
    assert CLASSIC_V1.fleet == (4, 3, 3, 2, 2, 2, 1, 1, 1, 1)
    assert CLASSIC_V1.placement_no_touch is True
    assert CLASSIC_V1.extra_turn_on_hit is True


def test_build_board_accepts_valid_classic_fleet() -> None:
    board = build_board_from_placements(CLASSIC_V1, _classic_valid_placements())
    assert board.ships_alive == 10


def test_build_board_rejects_wrong_fleet() -> None:
    placements = _classic_valid_placements()[:-1]
    with pytest.raises(ValueError, match="Fleet mismatch"):
        build_board_from_placements(CLASSIC_V1, placements)


def test_build_board_rejects_diagonal_touch() -> None:
    placements = _classic_valid_placements()
    placements[9] = Placement(1, 6, 1, "H")
    with pytest.raises(ValueError, match="cannot touch"):
        build_board_from_placements(CLASSIC_V1, placements)
