from app.engine.board import build_board_from_placements
from app.engine.game import BattleshipGame
from app.engine.types import Placement
from app.rulesets.catalog import CLASSIC_V1


def _classic_placements_left() -> list[Placement]:
    return [
        Placement(0, 0, 5, "H"),
        Placement(2, 0, 4, "H"),
        Placement(4, 0, 3, "H"),
        Placement(6, 0, 3, "H"),
        Placement(8, 0, 2, "H"),
    ]


def _classic_placements_right() -> list[Placement]:
    return [
        Placement(0, 5, 5, "H"),
        Placement(2, 6, 4, "H"),
        Placement(4, 7, 3, "H"),
        Placement(6, 7, 3, "H"),
        Placement(8, 8, 2, "H"),
    ]


def test_golden_classic_known_sequence_player0_wins_without_miss() -> None:
    board_p0 = build_board_from_placements(CLASSIC_V1, _classic_placements_left())
    board_p1 = build_board_from_placements(CLASSIC_V1, _classic_placements_right())
    game = BattleshipGame(CLASSIC_V1, board_p0, board_p1, first_player=0)

    shots = [
        (0, 5), (0, 6), (0, 7), (0, 8), (0, 9),
        (2, 6), (2, 7), (2, 8), (2, 9),
        (4, 7), (4, 8), (4, 9),
        (6, 7), (6, 8), (6, 9),
        (8, 8), (8, 9),
    ]
    expected = [
        "hit", "hit", "hit", "hit", "sunk",
        "hit", "hit", "hit", "sunk",
        "hit", "hit", "sunk",
        "hit", "hit", "sunk",
        "hit", "sunk",
    ]

    outcomes = [game.shoot(r, c).outcome for r, c in shots]

    assert outcomes == expected
    assert game.is_over is True
    assert game.winner == 0
