import pytest

from app.engine.board import build_board_from_placements
from app.engine.game import BattleshipGame
from app.engine.types import Placement
from app.rulesets.models import Ruleset

SIMPLE_RULESET = Ruleset(
    id="simple_v1",
    name="Simple",
    board_size=5,
    fleet=(2,),
    placement_no_touch=True,
    extra_turn_on_hit=False,
)


def _make_game() -> BattleshipGame:
    board_p0 = build_board_from_placements(SIMPLE_RULESET, [Placement(1, 1, 2, "H")])
    board_p1 = build_board_from_placements(SIMPLE_RULESET, [Placement(3, 1, 2, "H")])
    return BattleshipGame(SIMPLE_RULESET, board_p0=board_p0, board_p1=board_p1, first_player=0)


def test_turn_switches_on_miss_and_on_hit() -> None:
    game = _make_game()

    r1 = game.shoot(0, 0)
    assert r1.outcome == "miss"
    assert r1.next_player == 1

    r2 = game.shoot(1, 1)
    assert r2.outcome == "hit"
    assert r2.next_player == 0


def test_game_completes_and_blocks_extra_turns() -> None:
    game = _make_game()

    game.shoot(0, 0)
    game.shoot(1, 1)
    game.shoot(0, 1)
    end = game.shoot(1, 2)

    assert end.game_over is True
    assert end.winner == 1
    assert game.is_over is True

    with pytest.raises(RuntimeError, match="already over"):
        game.shoot(3, 1)
