from __future__ import annotations

import concurrent.futures
import math
import multiprocessing as mp
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


@dataclass(frozen=True, slots=True)
class _EvalRequest:
    ruleset_id: str
    seed: int
    strong_weights: dict[str, float]
    reference_weights: dict[str, float]
    league_opponents: list[dict[str, float]]
    baseline_games: int
    active_games: int


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
    return play_policy_vs(
        ruleset,
        rng,
        bot_a_kind="strong",
        bot_a_weights=strong_weights,
        bot_b_kind=opponent_kind,
        bot_b_weights=opponent_weights,
        first_player=first_player,
    )


def play_policy_vs(
    ruleset: Ruleset,
    rng: random.Random,
    *,
    bot_a_kind: str,
    bot_a_weights: dict[str, float] | None,
    bot_b_kind: str,
    bot_b_weights: dict[str, float] | None,
    first_player: int,
) -> MatchResult:
    placements_0 = generate_random_placements(ruleset, rng)
    placements_1 = generate_random_placements(ruleset, rng)

    board_p0 = build_board_from_placements(ruleset, placements_0)
    board_p1 = build_board_from_placements(ruleset, placements_1)
    game = BattleshipGame(ruleset=ruleset, board_p0=board_p0, board_p1=board_p1, first_player=first_player)

    def build_player(kind: str, weights: dict[str, float] | None):
        if kind == "random":
            return RandomBotPolicy(ruleset, rng=random.Random(rng.random()))
        if kind == "strong":
            return StrongBotPolicy(
                ruleset,
                rng=random.Random(rng.random()),
                weights=weights,
                config=StrongBotConfig(lookahead_mode="adaptive", lookahead_policy_version="adaptive_v1"),
            )
        raise ValueError(f"Unknown bot kind={kind}")

    player_a = build_player(bot_a_kind, bot_a_weights)
    player_b = build_player(bot_b_kind, bot_b_weights)

    players = [player_a, player_b]
    shots_total = 0

    while not game.is_over:
        current = game.current_player
        shot = players[current].select_shot()
        turn = game.shoot(*shot)
        players[current].observe_shot(shot, turn.outcome)
        shots_total += 1

        if shots_total > ruleset.board_size * ruleset.board_size * 4:
            raise RuntimeError("Self-play exceeded shot safety limit")

    assert game.winner is not None
    return MatchResult(winner=game.winner, shots_total=shots_total)


def _evaluate_candidate_window(payload: _EvalRequest) -> WindowMetrics:
    ruleset = get_ruleset(payload.ruleset_id)
    rng = random.Random(payload.seed)

    strong_weights = normalize_weights(payload.strong_weights)
    reference_weights = normalize_weights(payload.reference_weights)
    league_weights = [normalize_weights(item) for item in payload.league_opponents]

    baseline_wins = 0
    active_wins = 0
    won_turns: list[int] = []
    random_baseline_wins = 0
    strong_baseline_wins = 0

    random_baseline_games = max(1, payload.baseline_games // 2)
    strong_baseline_games = max(1, payload.baseline_games - random_baseline_games)

    for idx in range(random_baseline_games):
        first_player = idx % 2
        result = play_strong_vs(
            ruleset,
            rng,
            strong_weights=strong_weights,
            opponent_kind="random",
            opponent_weights=None,
            first_player=first_player,
        )
        if result.winner == 0:
            baseline_wins += 1
            random_baseline_wins += 1
            won_turns.append(result.shots_total)

    for idx in range(strong_baseline_games):
        first_player = idx % 2
        result = play_strong_vs(
            ruleset,
            rng,
            strong_weights=strong_weights,
            opponent_kind="strong",
            opponent_weights=normalize_weights(None),
            first_player=first_player,
        )
        if result.winner == 0:
            baseline_wins += 1
            strong_baseline_wins += 1
            won_turns.append(result.shots_total)

    for idx in range(payload.active_games):
        first_player = idx % 2
        if league_weights:
            opponent_weights = league_weights[idx % len(league_weights)]
        else:
            opponent_weights = reference_weights
        result = play_strong_vs(
            ruleset,
            rng,
            strong_weights=strong_weights,
            opponent_kind="strong",
            opponent_weights=opponent_weights,
            first_player=first_player,
        )
        if result.winner == 0:
            active_wins += 1
            won_turns.append(result.shots_total)

    wr_baseline = baseline_wins / max(1, payload.baseline_games)
    wr_active = active_wins / payload.active_games
    avg_turns_win = float(sum(won_turns) / len(won_turns)) if won_turns else ruleset.board_size * 7.0

    lcb_random = _wilson_lower_bound(wins=random_baseline_wins, total=random_baseline_games)
    lcb_strong = _wilson_lower_bound(wins=strong_baseline_wins, total=strong_baseline_games)
    lcb_active = _wilson_lower_bound(wins=active_wins, total=payload.active_games)
    score = compute_score(
        wr_baseline=wr_baseline,
        wr_active=wr_active,
        avg_turns_win=avg_turns_win,
        lcb_random=lcb_random,
        lcb_strong=lcb_strong,
        lcb_active=lcb_active,
    )
    return WindowMetrics(
        wr_baseline=round(wr_baseline, 6),
        wr_active=round(wr_active, 6),
        avg_turns_win=round(avg_turns_win, 6),
        score=round(score, 6),
    )


def _wilson_lower_bound(*, wins: int, total: int, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    p = wins / total
    z2 = z * z
    denom = 1 + z2 / total
    center = p + z2 / (2 * total)
    margin = z * math.sqrt((p * (1 - p) + z2 / (4 * total)) / total)
    return max(0.0, (center - margin) / denom)


class SelfPlaySimulator:
    _ELITE_FRACTION = 0.25

    def __init__(
        self,
        *,
        ruleset_id: str,
        seed: int,
        window_games: int,
        population_size: int,
        train_split: float,
        worker_count: int,
        seed_weights: dict[str, float] | None = None,
    ) -> None:
        self._ruleset = get_ruleset(ruleset_id)
        self._ruleset_id = ruleset_id
        self._seed = seed
        self._rng = random.Random(seed)
        self._window_games = max(4, window_games)
        self._population_size = max(1, population_size)
        self._train_split = min(0.9, max(0.5, train_split))
        self._worker_count = max(1, worker_count)

        base = normalize_weights(seed_weights)
        self._incumbent_weights = dict(base)
        self._incumbent_score = 0.0
        self._best_weights = dict(base)
        self._best_score = 0.0

        self._executor: concurrent.futures.ProcessPoolExecutor | None = None
        if self._worker_count > 1:
            ctx = mp.get_context("spawn")
            self._executor = concurrent.futures.ProcessPoolExecutor(
                max_workers=self._worker_count,
                mp_context=ctx,
            )

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    def __del__(self) -> None:
        self.close()

    @property
    def best_weights(self) -> dict[str, float]:
        return dict(self._best_weights)

    @property
    def current_weights(self) -> dict[str, float]:
        return dict(self._incumbent_weights)

    def next_window(
        self,
        windows_done: int,
        *,
        league_opponents: list[dict[str, float]] | None = None,
    ) -> WindowMetrics:
        sigma = max(0.02, 0.20 * (0.988 ** windows_done))

        reference = dict(self._incumbent_weights)
        candidates = [dict(reference)]
        for _ in range(self._population_size - 1):
            candidates.append(mutate_weights(self._rng, reference, sigma))

        train_games = int(round(self._window_games * self._train_split))
        train_games = max(2, min(self._window_games - 2, train_games))
        eval_games = max(2, self._window_games - train_games)

        train_baseline = max(1, train_games // 2)
        train_active = max(1, train_games - train_baseline)
        eval_baseline = max(1, eval_games // 2)
        eval_active = max(1, eval_games - eval_baseline)

        normalized_league = [normalize_weights(item) for item in (league_opponents or [])]

        train_metrics = self._evaluate_population(
            windows_done=windows_done,
            candidates=candidates,
            reference_weights=reference,
            league_opponents=normalized_league,
            baseline_games=train_baseline,
            active_games=train_active,
            phase_tag=0,
        )

        elite_count = max(1, math.ceil(len(candidates) * self._ELITE_FRACTION))
        ranked = sorted(
            range(len(candidates)),
            key=lambda idx: (train_metrics[idx].score, -idx),
            reverse=True,
        )
        elite_indices = ranked[:elite_count]

        elite_eval: dict[int, WindowMetrics] = {}
        for candidate_index in elite_indices:
            elite_eval[candidate_index] = self._evaluate_one(
                windows_done=windows_done,
                candidate_index=candidate_index,
                candidate_weights=candidates[candidate_index],
                reference_weights=reference,
                league_opponents=normalized_league,
                baseline_games=eval_baseline,
                active_games=eval_active,
                phase_tag=1,
            )

        best_eval_index = max(
            elite_indices,
            key=lambda idx: (elite_eval[idx].score, train_metrics[idx].score, -idx),
        )
        eval_metrics = elite_eval[best_eval_index]
        if eval_metrics.score >= self._incumbent_score:
            self._incumbent_weights = dict(candidates[best_eval_index])
            self._incumbent_score = eval_metrics.score

        if eval_metrics.score >= self._best_score:
            self._best_weights = dict(self._incumbent_weights)
            self._best_score = eval_metrics.score

        return eval_metrics

    def _evaluate_population(
        self,
        *,
        windows_done: int,
        candidates: list[dict[str, float]],
        reference_weights: dict[str, float],
        league_opponents: list[dict[str, float]],
        baseline_games: int,
        active_games: int,
        phase_tag: int,
    ) -> list[WindowMetrics]:
        if self._executor is None or len(candidates) == 1:
            return [
                self._evaluate_one(
                    windows_done=windows_done,
                    candidate_index=index,
                    candidate_weights=candidate,
                    reference_weights=reference_weights,
                    league_opponents=league_opponents,
                    baseline_games=baseline_games,
                    active_games=active_games,
                    phase_tag=phase_tag,
                )
                for index, candidate in enumerate(candidates)
            ]

        futures: list[concurrent.futures.Future[WindowMetrics]] = []
        for index, candidate in enumerate(candidates):
            request = _EvalRequest(
                ruleset_id=self._ruleset_id,
                seed=self._seed_for(windows_done, index, phase_tag),
                strong_weights=candidate,
                reference_weights=reference_weights,
                league_opponents=league_opponents,
                baseline_games=baseline_games,
                active_games=active_games,
            )
            futures.append(self._executor.submit(_evaluate_candidate_window, request))

        return [future.result() for future in futures]

    def _evaluate_one(
        self,
        *,
        windows_done: int,
        candidate_index: int,
        candidate_weights: dict[str, float],
        reference_weights: dict[str, float],
        league_opponents: list[dict[str, float]],
        baseline_games: int,
        active_games: int,
        phase_tag: int,
    ) -> WindowMetrics:
        request = _EvalRequest(
            ruleset_id=self._ruleset_id,
            seed=self._seed_for(windows_done, candidate_index, phase_tag),
            strong_weights=candidate_weights,
            reference_weights=reference_weights,
            league_opponents=league_opponents,
            baseline_games=baseline_games,
            active_games=active_games,
        )
        return _evaluate_candidate_window(request)

    def _seed_for(self, windows_done: int, candidate_index: int, phase_tag: int) -> int:
        return (
            self._seed * 1_000_003
            + (windows_done + 1) * 100_003
            + candidate_index * 977
            + phase_tag * 10_007
        )
