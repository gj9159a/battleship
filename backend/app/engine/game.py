from app.engine.board import Board
from app.engine.types import TurnResult
from app.rulesets.models import Ruleset


class BattleshipGame:
    def __init__(self, ruleset: Ruleset, board_p0: Board, board_p1: Board, first_player: int = 0) -> None:
        if first_player not in (0, 1):
            raise ValueError("first_player must be 0 or 1")
        self.ruleset = ruleset
        self._boards = [board_p0, board_p1]
        self._current_player = first_player
        self._winner: int | None = None

    @property
    def current_player(self) -> int:
        return self._current_player

    @property
    def winner(self) -> int | None:
        return self._winner

    @property
    def is_over(self) -> bool:
        return self._winner is not None

    def shoot(self, row: int, col: int) -> TurnResult:
        if self.is_over:
            raise RuntimeError("Game is already over")

        shooter = self._current_player
        target = 1 - shooter
        shot_result = self._boards[target].fire((row, col))

        game_over = self._boards[target].all_sunk
        if game_over:
            self._winner = shooter
        elif shot_result.outcome == "miss" or not self.ruleset.extra_turn_on_hit:
            self._current_player = target

        return TurnResult(
            shooter=shooter,
            target=target,
            row=row,
            col=col,
            outcome=shot_result.outcome,
            game_over=game_over,
            winner=self._winner,
            next_player=self._current_player,
        )
