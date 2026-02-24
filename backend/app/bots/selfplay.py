from __future__ import annotations

import random
from dataclasses import dataclass

from app.engine.board import Board, build_board_from_placements
from app.engine.game import BattleshipGame
from app.engine.types import Placement
from app.rulesets import get_ruleset
from app.rulesets.models import Ruleset
from app.trainer.simulation import WindowMetrics, compute_score

from .policy import RandomBotPolicy, StrongBotConfig, StrongBotPolicy, normalize_weights


@dataclass(frozen=True, slots=True)
class MatchResult:
    winner: int
    shots_total: int


def mutate_weights(rng: random.Random, source: dict[str, float], sigma: float) -> dict[str, float]:
    mutated: dict[str, float] = {}
    for key, value in normalize_weights(source).items():
        delta = rng.gauss(0.0, sigma)
        candidate = max(0.01, min(2.5, value + delta))
        mutated[key] = round(candidate, 6)
    return mutated


def generate_random_placements(ruleset: Ruleset, rng: random.Random) -> list[Placement]:
    placements: list[Placement] = []
    board_size = ruleset.board_size
    board = Board(size=ruleset.board_size, no_touch=ruleset.placement_no_touch)

    for length in ruleset.fleet:
        placed = False
        for _ in range(500):
            orientation = "H" if rng.random() < 0.5 else "V"
            max_row = board_size - (length if orientation == "V" else 1)
            max_col = board_size - (length if orientation == "H" else 1)
            row = rng.randint(0, max_row)
            col = rng.randint(0, max_col)
            candidate = Placement(row=row, col=col, length=length, orientation=orientation)
            try:
                board.place_ship(candidate)
                placements.append(candidate)
                placed = True
                break
            except ValueError:
                continue

        if not placed:
            raise RuntimeError(f"Failed to place ship length={length} for ruleset={ruleset.id}")

    return placements


def play_strong_vs(
    ruleset: Ruleset,
    rng: random.Random,
    *,
    strong_weights: dict[str, float],
    opponent_kind: str,
    opponent_weights: dict[str, float] | None,
    first_player: int,
) -> MatchResult:
    placements_0 = generate_random_placements(ruleset, rng)
    placements_1 = generate_random_placements(ruleset, rng)

    board_p0 = build_board_from_placements(ruleset, placements_0)
    board_p1 = build_board_from_placements(ruleset, placements_1)
    game = BattleshipGame(ruleset=ruleset, board_p0=board_p0, board_p1=board_p1, first_player=first_player)

    strong_player = StrongBotPolicy(
        ruleset,
        rng=random.Random(rng.random()),
        weights=strong_weights,
        config=StrongBotConfig(lookahead_mode="adaptive", lookahead_policy_version="adaptive_v1"),
    )

    if opponent_kind == "random":
        opponent = RandomBotPolicy(ruleset, rng=random.Random(rng.random()))
    elif opponent_kind == "strong":
        opponent = StrongBotPolicy(
            ruleset,
            rng=random.Random(rng.random()),
            weights=opponent_weights,
            config=StrongBotConfig(lookahead_mode="adaptive", lookahead_policy_version="adaptive_v1"),
        )
    else:
        raise ValueError(f"Unknown opponent_kind={opponent_kind}")

    players = [strong_player, opponent]
    shots_total = 0

    while not game.is_over:
        current = game.current_player
        shot = players[current].select_shot()
        turn = game.shoot(*shot)
        players[current].observe_shot(shot, turn.outcome)
        shots_total += 1

        if shots_total > ruleset.board_size * ruleset.board_size * 4:
            # Defensive bound: should never happen under valid logic.
            raise RuntimeError("Self-play exceeded shot safety limit")

    assert game.winner is not None
    return MatchResult(winner=game.winner, shots_total=shots_total)


class SelfPlaySimulator:
    def __init__(
        self,
        *,
        ruleset_id: str,
        seed: int,
        window_games: int,
        seed_weights: dict[str, float] | None = None,
    ) -> None:
        self._ruleset = get_ruleset(ruleset_id)
        self._rng = random.Random(seed)
        self._window_games = max(4, window_games)

        base = normalize_weights(seed_weights)
        self._incumbent_weights = dict(base)
        self._incumbent_score = 0.0
        self._best_weights = dict(base)
        self._best_score = 0.0

    @property
    def best_weights(self) -> dict[str, float]:
        return dict(self._best_weights)

    @property
    def current_weights(self) -> dict[str, float]:
        return dict(self._incumbent_weights)

    def next_window(self, windows_done: int) -> WindowMetrics:
        sigma = max(0.02, 0.18 * (0.985 ** windows_done))
        candidate = mutate_weights(self._rng, self._incumbent_weights, sigma)

        baseline_games = max(2, self._window_games // 2)
        active_games = max(2, self._window_games - baseline_games)

        baseline_wins = 0
        active_wins = 0
        won_turns: list[int] = []

        for idx in range(baseline_games):
            first_player = idx % 2
            opponent_kind = "random" if idx % 2 == 0 else "strong"
            baseline_weights = None if opponent_kind == "random" else normalize_weights(None)
            result = play_strong_vs(
                self._ruleset,
                self._rng,
                strong_weights=candidate,
                opponent_kind=opponent_kind,
                opponent_weights=baseline_weights,
                first_player=first_player,
            )
            if result.winner == 0:
                baseline_wins += 1
                won_turns.append(result.shots_total)

        for idx in range(active_games):
            first_player = idx % 2
            result = play_strong_vs(
                self._ruleset,
                self._rng,
                strong_weights=candidate,
                opponent_kind="strong",
                opponent_weights=self._incumbent_weights,
                first_player=first_player,
            )
            if result.winner == 0:
                active_wins += 1
                won_turns.append(result.shots_total)

        wr_baseline = baseline_wins / baseline_games
        wr_active = active_wins / active_games
        avg_turns_win = float(sum(won_turns) / len(won_turns)) if won_turns else self._ruleset.board_size * 7.0
        score = compute_score(wr_baseline, wr_active, avg_turns_win)

        if score >= self._incumbent_score:
            self._incumbent_weights = dict(candidate)
            self._incumbent_score = score

        if score >= self._best_score:
            self._best_weights = dict(candidate)
            self._best_score = score

        return WindowMetrics(
            wr_baseline=round(wr_baseline, 6),
            wr_active=round(wr_active, 6),
            avg_turns_win=round(avg_turns_win, 6),
            score=round(score, 6),
        )
