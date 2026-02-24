from dataclasses import dataclass, field
from uuid import uuid4

from app.engine.board import build_board_from_placements
from app.engine.game import BattleshipGame
from app.engine.types import Placement, TurnResult
from app.rulesets import get_ruleset


@dataclass(slots=True)
class GameSession:
    id: str
    ruleset_id: str
    game: BattleshipGame
    shots: list[TurnResult] = field(default_factory=list)


class GameSessionService:
    def __init__(self) -> None:
        self._sessions: dict[str, GameSession] = {}

    def create_session(
        self,
        ruleset_id: str,
        player_placements: list[Placement],
        opponent_placements: list[Placement],
        first_player: int,
    ) -> GameSession:
        ruleset = get_ruleset(ruleset_id)
        board_p0 = build_board_from_placements(ruleset, player_placements)
        board_p1 = build_board_from_placements(ruleset, opponent_placements)
        game = BattleshipGame(ruleset=ruleset, board_p0=board_p0, board_p1=board_p1, first_player=first_player)
        session = GameSession(id=str(uuid4()), ruleset_id=ruleset_id, game=game)
        self._sessions[session.id] = session
        return session

    def get_session(self, session_id: str) -> GameSession:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise KeyError(f"Unknown game session id={session_id}") from exc

    def shoot(self, session_id: str, row: int, col: int) -> TurnResult:
        session = self.get_session(session_id)
        turn_result = session.game.shoot(row=row, col=col)
        session.shots.append(turn_result)
        return turn_result
