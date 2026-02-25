import random
from dataclasses import dataclass, field
from uuid import uuid4

from app.bots.policy import RandomBotPolicy, StrongBotConfig, StrongBotPolicy, normalize_weights
from app.bots.selfplay import generate_random_placements
from app.engine.board import build_board_from_placements
from app.engine.game import BattleshipGame
from app.engine.types import Placement, TurnResult
from app.rulesets import get_ruleset
from app.services.bot_catalog import BotCatalogService
from app.services.league import LeagueService


BotPolicy = RandomBotPolicy | StrongBotPolicy


@dataclass(slots=True)
class GameSession:
    id: str
    ruleset_id: str
    player_placements: list[Placement]
    opponent_bot_version_id: str | None
    game: BattleshipGame
    opponent_policy: BotPolicy
    shots: list[TurnResult] = field(default_factory=list)


class GameSessionService:
    def __init__(
        self,
        *,
        bot_catalog: BotCatalogService | None = None,
        league_service: LeagueService | None = None,
    ) -> None:
        self._sessions: dict[str, GameSession] = {}
        self._bot_catalog = bot_catalog
        self._league_service = league_service

    def create_session(
        self,
        ruleset_id: str,
        first_player: int | None = None,
    ) -> GameSession:
        ruleset = get_ruleset(ruleset_id)
        seed = random.SystemRandom().randint(1, 2_147_483_647)
        rng = random.Random(seed)
        resolved_first_player = first_player if first_player in (0, 1) else rng.randint(0, 1)
        player_placements = generate_random_placements(ruleset, rng)
        opponent_placements = generate_random_placements(ruleset, rng)
        board_p0 = build_board_from_placements(ruleset, player_placements)
        board_p1 = build_board_from_placements(ruleset, opponent_placements)
        opponent_kind, opponent_weights, opponent_bot_version_id = self._select_opponent_policy(ruleset_id)
        if opponent_kind == "random":
            opponent_policy: BotPolicy = RandomBotPolicy(ruleset, rng=random.Random(seed + 100_003))
        else:
            opponent_policy = StrongBotPolicy(
                ruleset,
                rng=random.Random(seed + 200_003),
                weights=opponent_weights,
                config=StrongBotConfig(lookahead_mode="adaptive", lookahead_policy_version="adaptive_v1"),
            )
        game = BattleshipGame(ruleset=ruleset, board_p0=board_p0, board_p1=board_p1, first_player=resolved_first_player)
        session = GameSession(
            id=str(uuid4()),
            ruleset_id=ruleset_id,
            player_placements=player_placements,
            opponent_bot_version_id=opponent_bot_version_id,
            game=game,
            opponent_policy=opponent_policy,
        )
        self._sessions[session.id] = session
        return session

    def get_session(self, session_id: str) -> GameSession:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise KeyError(f"Unknown game session id={session_id}") from exc

    def shoot(self, session_id: str, row: int, col: int) -> TurnResult:
        session = self.get_session(session_id)
        if session.game.current_player == 1:
            bot_row, bot_col = session.opponent_policy.select_shot()
            turn_result = session.game.shoot(row=bot_row, col=bot_col)
            session.opponent_policy.observe_shot((bot_row, bot_col), turn_result.outcome)
        else:
            turn_result = session.game.shoot(row=row, col=col)
        session.shots.append(turn_result)
        return turn_result

    def _select_opponent_policy(self, ruleset_id: str) -> tuple[str, dict[str, float] | None, str | None]:
        if self._league_service is not None and self._bot_catalog is not None:
            table = self._league_service.list_table(ruleset_id)
            for row in table:
                if row.pool_type != "league":
                    continue
                try:
                    bot = self._bot_catalog.get_bot(row.bot_version_id)
                except KeyError:
                    continue
                if bot.policy_type == "random":
                    return "random", None, bot.bot_version_id
                return "strong", dict(bot.weights), bot.bot_version_id

        baseline_id = f"{ruleset_id}-baseline-strong"
        if self._bot_catalog is not None:
            try:
                baseline = self._bot_catalog.get_bot(baseline_id)
            except KeyError:
                baseline = None
            if baseline is not None:
                return "strong", dict(baseline.weights), baseline.bot_version_id

        return "strong", normalize_weights(None), None
