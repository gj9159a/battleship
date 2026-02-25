from __future__ import annotations

import base64
import concurrent.futures
import math
import multiprocessing as mp
import pickle
import random
from dataclasses import dataclass, replace

from app.engine.board import Board, build_board_from_placements
from app.engine.game import BattleshipGame
from app.engine.types import Placement
from app.rulesets import get_ruleset
from app.rulesets.models import Ruleset
from app.trainer.simulation import (
    SelectionDecision,
    WindowMetrics,
    challenger_is_better,
    compute_score,
    select_incumbent_lexicographic,
)

from .policy import RandomBotPolicy, StrongBotConfig, StrongBotPolicy, normalize_weights


@dataclass(frozen=True, slots=True)
class MatchResult:
    winner: int
    shots_total: int
    bot_stats: tuple["_BotAttackStats", "_BotAttackStats"]


@dataclass(frozen=True, slots=True)
class _BotAttackStats:
    shots_fired: int
    shots_to_first_hit: int | None
    misses_before_first_hit: int
    shots_to_sink_all: int | None
    shots_after_first_hit_to_sink_all: int | None


@dataclass(frozen=True, slots=True)
class _EvalRequest:
    ruleset_id: str
    seed: int
    strong_weights: dict[str, float]
    reference_weights: dict[str, float]
    league_opponents: list[dict[str, float]]
    baseline_games: int
    active_games: int


@dataclass(frozen=True, slots=True)
class _PairedEvalResult:
    candidate_index: int
    candidate_metrics: WindowMetrics
    incumbent_metrics: WindowMetrics
    selection_decision: SelectionDecision


@dataclass(frozen=True, slots=True)
class FrozenSuiteAggregate:
    wins: int
    total_games: int
    winrate: float
    lcb: float
    avg_shots_to_sink_all: float
    p95_shots_to_sink_all: float
    avg_shots_to_first_hit: float
    avg_shots_after_first_hit_to_sink_all: float
    avg_misses_before_first_hit: float
    eval_seed_anchor: int
    seed_count: int
    games_per_seed: int
    paired_eval: bool
    mirrored_first_player: bool


@dataclass(frozen=True, slots=True)
class _RestartAnchor:
    weights: dict[str, float]
    robust_score: float
    eval_protocol_hash: str
    windows_done: int
    insertion_index: int


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
    shots_by_player = [0, 0]
    first_hit_shot: list[int | None] = [None, None]
    misses_before_first_hit = [0, 0]

    while not game.is_over:
        current = game.current_player
        shot = players[current].select_shot()
        turn = game.shoot(*shot)
        players[current].observe_shot(shot, turn.outcome)
        shots_total += 1
        shots_by_player[current] += 1
        if first_hit_shot[current] is None:
            if turn.outcome in {"hit", "sunk"}:
                first_hit_shot[current] = shots_by_player[current]
            elif turn.outcome == "miss":
                misses_before_first_hit[current] += 1

        if shots_total > ruleset.board_size * ruleset.board_size * 4:
            raise RuntimeError("Self-play exceeded shot safety limit")

    assert game.winner is not None

    def build_attack_stats(player: int) -> _BotAttackStats:
        shots_fired = shots_by_player[player]
        shots_to_first_hit = first_hit_shot[player]
        shots_to_sink_all = shots_fired if game.winner == player else None
        shots_after_first_hit_to_sink_all = None
        if shots_to_sink_all is not None and shots_to_first_hit is not None:
            shots_after_first_hit_to_sink_all = max(0, shots_to_sink_all - shots_to_first_hit)
        return _BotAttackStats(
            shots_fired=shots_fired,
            shots_to_first_hit=shots_to_first_hit,
            misses_before_first_hit=misses_before_first_hit[player],
            shots_to_sink_all=shots_to_sink_all,
            shots_after_first_hit_to_sink_all=shots_after_first_hit_to_sink_all,
        )

    return MatchResult(
        winner=game.winner,
        shots_total=shots_total,
        bot_stats=(build_attack_stats(0), build_attack_stats(1)),
    )


def _evaluate_candidate_window(payload: _EvalRequest) -> WindowMetrics:
    ruleset = get_ruleset(payload.ruleset_id)
    rng = random.Random(payload.seed)

    strong_weights = normalize_weights(payload.strong_weights)
    reference_weights = normalize_weights(payload.reference_weights)
    league_weights = [normalize_weights(item) for item in payload.league_opponents]

    baseline_wins = 0
    active_wins = 0
    shots_to_sink_all_values: list[int] = []
    shots_to_first_hit_values: list[int] = []
    shots_after_first_hit_to_sink_all_values: list[int] = []
    misses_before_first_hit_values: list[int] = []
    random_baseline_wins = 0
    strong_baseline_wins = 0

    def collect_attack_metrics(result: MatchResult) -> None:
        stats = result.bot_stats[0]
        misses_before_first_hit_values.append(stats.misses_before_first_hit)
        shots_to_first_hit_values.append(stats.shots_to_first_hit if stats.shots_to_first_hit is not None else stats.shots_fired)
        if stats.shots_to_sink_all is not None:
            shots_to_sink_all_values.append(stats.shots_to_sink_all)
        if stats.shots_after_first_hit_to_sink_all is not None:
            shots_after_first_hit_to_sink_all_values.append(stats.shots_after_first_hit_to_sink_all)

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
        collect_attack_metrics(result)
        if result.winner == 0:
            baseline_wins += 1
            random_baseline_wins += 1

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
        collect_attack_metrics(result)
        if result.winner == 0:
            baseline_wins += 1
            strong_baseline_wins += 1

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
        collect_attack_metrics(result)
        if result.winner == 0:
            active_wins += 1

    wr_baseline = baseline_wins / max(1, payload.baseline_games)
    wr_active = active_wins / payload.active_games
    default_shot_budget = float(ruleset.board_size * ruleset.board_size)
    avg_shots_to_sink_all = _average(shots_to_sink_all_values, default_shot_budget)
    p95_shots_to_sink_all = _p95(shots_to_sink_all_values, default_shot_budget)
    avg_shots_to_first_hit = _average(shots_to_first_hit_values, default_shot_budget)
    avg_shots_after_first_hit_to_sink_all = _average(shots_after_first_hit_to_sink_all_values, default_shot_budget)
    avg_misses_before_first_hit = _average(misses_before_first_hit_values, default_shot_budget)
    avg_turns_win = avg_shots_to_sink_all

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
        avg_shots_to_sink_all=round(avg_shots_to_sink_all, 6),
        p95_shots_to_sink_all=round(p95_shots_to_sink_all, 6),
        avg_shots_to_first_hit=round(avg_shots_to_first_hit, 6),
        avg_shots_after_first_hit_to_sink_all=round(avg_shots_after_first_hit_to_sink_all, 6),
        avg_misses_before_first_hit=round(avg_misses_before_first_hit, 6),
        eval_seed_anchor=payload.seed,
        incumbent_seed_anchor=payload.seed,
        paired_eval=False,
        mirrored_first_player=True,
        lcb_random=round(lcb_random, 6),
        lcb_strong=round(lcb_strong, 6),
        lcb_active=round(lcb_active, 6),
    )


def _average(values: list[int], fallback: float) -> float:
    if not values:
        return fallback
    return float(sum(values) / len(values))


def _p95(values: list[int], fallback: float) -> float:
    if not values:
        return fallback
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return float(ordered[index])


def _derive_suite_seed(seed_anchor: int, seed_index: int, derivation_scheme: str) -> int:
    if derivation_scheme == "anchor_plus_index_mul_1009_v1":
        return seed_anchor + seed_index * 1009
    if derivation_scheme == "anchor_plus_index_v1":
        return seed_anchor + seed_index
    raise ValueError(f"Unsupported seed derivation scheme: {derivation_scheme}")


def run_frozen_suite(
    *,
    ruleset: Ruleset,
    subject_weights: dict[str, float],
    opponent_kind: str,
    opponent_weights: dict[str, float] | None,
    seed_anchor: int,
    seed_count: int,
    seed_derivation_scheme: str,
    games_per_seed: int,
    mirrored_first_player: bool,
) -> FrozenSuiteAggregate:
    if seed_count <= 0:
        raise ValueError("seed_count must be > 0")
    if games_per_seed <= 0:
        raise ValueError("games_per_seed must be > 0")

    normalized_subject = normalize_weights(subject_weights)
    normalized_opponent = normalize_weights(opponent_weights) if opponent_kind == "strong" else None

    wins = 0
    total_games = 0
    shots_to_sink_all_values: list[int] = []
    shots_to_first_hit_values: list[int] = []
    shots_after_first_hit_to_sink_all_values: list[int] = []
    misses_before_first_hit_values: list[int] = []
    default_shot_budget = float(ruleset.board_size * ruleset.board_size)

    for seed_index in range(seed_count):
        base_seed = _derive_suite_seed(seed_anchor, seed_index, seed_derivation_scheme)
        for game_index in range(games_per_seed):
            first_player = (game_index % 2) if mirrored_first_player else 0
            rng = random.Random(base_seed + game_index * 131 + 17)
            result = play_strong_vs(
                ruleset,
                rng,
                strong_weights=normalized_subject,
                opponent_kind=opponent_kind,
                opponent_weights=normalized_opponent,
                first_player=first_player,
            )
            total_games += 1
            if result.winner == 0:
                wins += 1

            stats = result.bot_stats[0]
            misses_before_first_hit_values.append(stats.misses_before_first_hit)
            shots_to_first_hit_values.append(
                stats.shots_to_first_hit if stats.shots_to_first_hit is not None else stats.shots_fired
            )
            if stats.shots_to_sink_all is not None:
                shots_to_sink_all_values.append(stats.shots_to_sink_all)
            if stats.shots_after_first_hit_to_sink_all is not None:
                shots_after_first_hit_to_sink_all_values.append(stats.shots_after_first_hit_to_sink_all)

    total_games = max(1, total_games)
    winrate = wins / total_games
    lcb = _wilson_lower_bound(wins=wins, total=total_games)
    return FrozenSuiteAggregate(
        wins=wins,
        total_games=total_games,
        winrate=round(winrate, 6),
        lcb=round(lcb, 6),
        avg_shots_to_sink_all=round(_average(shots_to_sink_all_values, default_shot_budget), 6),
        p95_shots_to_sink_all=round(_p95(shots_to_sink_all_values, default_shot_budget), 6),
        avg_shots_to_first_hit=round(_average(shots_to_first_hit_values, default_shot_budget), 6),
        avg_shots_after_first_hit_to_sink_all=round(
            _average(shots_after_first_hit_to_sink_all_values, default_shot_budget), 6
        ),
        avg_misses_before_first_hit=round(_average(misses_before_first_hit_values, default_shot_budget), 6),
        eval_seed_anchor=seed_anchor,
        seed_count=seed_count,
        games_per_seed=games_per_seed,
        paired_eval=False,
        mirrored_first_player=mirrored_first_player,
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
    _SEARCH_POLICY = "sep_cma_es_lite_v1"
    _WEIGHT_MIN = 0.01
    _WEIGHT_MAX = 2.5
    _CMA_TINY = 1e-12
    _CMA_SIGMA_INIT = 0.20
    _CMA_SIGMA_MIN = 0.02
    _CMA_SIGMA_MAX = 0.45
    _CMA_DIAG_MIN = 0.05
    _CMA_DIAG_MAX = 4.0
    _CMA_C_SIGMA = 0.3
    _CMA_D_SIGMA = 1.0
    _CMA_C_COV = 0.2
    _CMA_RESTART_SIGMA = 0.12
    _ANCHOR_ARCHIVE_LIMIT = 8
    _MAX_RESTARTS = 3
    _SEARCH_STATE_VERSION = "sep_cma_es_lite_v1"

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
        seed_best_weights: dict[str, float] | None = None,
        seed_best_score: float = 0.0,
        search_state: dict | None = None,
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
        self._param_names = tuple(base.keys())
        self._incumbent_weights = dict(base)
        self._incumbent_score = 0.0
        self._best_weights = (
            dict(normalize_weights(seed_best_weights)) if seed_best_weights is not None else dict(base)
        )
        self._best_score = float(seed_best_score)
        self._cma_mean = dict(base)
        self._cma_sigma = self._CMA_SIGMA_INIT
        self._cma_diag = {name: 1.0 for name in self._param_names}
        self._cma_p_sigma = {name: 0.0 for name in self._param_names}
        self._cma_generation = 0
        self._last_cma_parent_mu = 0
        self._last_cma_mueff = 0.0
        self._restart_count = 0
        self._last_restart_reason = "none"
        self._last_restart_anchor_score = 0.0
        self._last_restart_window = -1
        self._elite_fallback_used = False
        self._anchor_archive: list[_RestartAnchor] = []
        self._anchor_insert_counter = 0

        self._executor: concurrent.futures.ProcessPoolExecutor | None = None
        if self._worker_count > 1:
            ctx = mp.get_context("spawn")
            self._executor = concurrent.futures.ProcessPoolExecutor(
                max_workers=self._worker_count,
                mp_context=ctx,
            )

        if search_state is not None:
            self.restore_search_state(search_state)

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

    @property
    def population_size(self) -> int:
        return self._population_size

    def set_population_size(self, population_size: int) -> None:
        self._population_size = max(1, int(population_size))

    def maybe_restart(
        self,
        *,
        plateau_windows: int,
        restart_trigger_plateau_windows: int,
        eval_protocol_hash: str,
        windows_done: int,
    ) -> bool:
        if plateau_windows < restart_trigger_plateau_windows:
            return False
        if self._restart_count >= self._MAX_RESTARTS:
            return False
        if self._last_restart_window == windows_done:
            return False

        anchor = self._select_restart_anchor(eval_protocol_hash=eval_protocol_hash)
        if anchor is None:
            return False

        self._incumbent_weights = dict(anchor.weights)
        self._cma_mean = dict(anchor.weights)
        self._cma_sigma = max(self._cma_sigma, self._CMA_RESTART_SIGMA)
        self._cma_diag = {name: 1.0 for name in self._param_names}
        self._cma_p_sigma = {name: 0.0 for name in self._param_names}
        self._cma_generation = 0
        self._last_cma_parent_mu = 0
        self._last_cma_mueff = 0.0
        self._restart_count += 1
        self._last_restart_reason = "plateau_restart"
        self._last_restart_anchor_score = anchor.robust_score
        self._last_restart_window = windows_done
        return True

    def next_window(
        self,
        windows_done: int,
        *,
        eval_protocol_hash: str,
        league_opponents: list[dict[str, float]] | None = None,
    ) -> WindowMetrics:
        reference = dict(self._incumbent_weights)
        candidates = [dict(reference)]
        for _ in range(self._population_size - 1):
            candidates.append(self._sample_challenger())

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
        self._update_cma_from_ranked_candidates(candidates=candidates, ranked_indices=ranked)
        elite_indices = ranked[:elite_count]
        challenger_indices = [idx for idx in elite_indices if idx != 0]
        elite_fallback_used = False
        if not challenger_indices and len(candidates) > 1:
            for idx in ranked:
                if idx != 0:
                    challenger_indices = [idx]
                    elite_fallback_used = True
                    break
        self._elite_fallback_used = elite_fallback_used

        eval_seed_anchor = self._seed_for(windows_done, 0, 1)
        incumbent_eval_metrics = self._evaluate_one(
            windows_done=windows_done,
            candidate_index=0,
            candidate_weights=reference,
            reference_weights=reference,
            league_opponents=normalized_league,
            baseline_games=eval_baseline,
            active_games=eval_active,
            phase_tag=1,
            seed_anchor=eval_seed_anchor,
        )
        incumbent_eval_metrics = replace(
            incumbent_eval_metrics,
            eval_seed_anchor=eval_seed_anchor,
            incumbent_seed_anchor=eval_seed_anchor,
            paired_eval=True,
            mirrored_first_player=True,
        )
        if not self._has_anchor_for_protocol(eval_protocol_hash):
            self._record_anchor(
                weights=reference,
                robust_score=incumbent_eval_metrics.score,
                eval_protocol_hash=eval_protocol_hash,
                windows_done=windows_done,
            )

        best_pair_result: _PairedEvalResult | None = None
        for candidate_index in challenger_indices:
            paired_result = self._evaluate_paired(
                windows_done=windows_done,
                candidate_index=candidate_index,
                candidate_weights=candidates[candidate_index],
                reference_weights=reference,
                league_opponents=normalized_league,
                baseline_games=eval_baseline,
                active_games=eval_active,
                phase_tag=1,
                seed_anchor=eval_seed_anchor,
                incumbent_metrics=incumbent_eval_metrics,
            )
            if best_pair_result is None:
                best_pair_result = paired_result
                continue
            if challenger_is_better(
                paired_result.selection_decision,
                left_index=candidate_index,
                right=best_pair_result.selection_decision,
                right_index=best_pair_result.candidate_index,
            ):
                best_pair_result = paired_result

        if best_pair_result is None:
            incumbent_eval_metrics = replace(
                incumbent_eval_metrics,
                selection_decision_reason="no_elite_challenger",
                elite_candidates_evaluated=0,
                elite_selected_candidate_index=-1,
                elite_selection_reason="no_elite_challenger",
                **self._window_search_fields(),
            )
            eval_metrics = incumbent_eval_metrics
            self._incumbent_score = incumbent_eval_metrics.score
            if eval_metrics.score >= self._best_score:
                self._best_weights = dict(self._incumbent_weights)
                self._best_score = eval_metrics.score
            return eval_metrics

        eval_metrics: WindowMetrics
        if best_pair_result.selection_decision.select_candidate:
            self._incumbent_weights = dict(candidates[best_pair_result.candidate_index])
            self._incumbent_score = best_pair_result.candidate_metrics.score
            eval_metrics = best_pair_result.candidate_metrics
            self._record_anchor(
                weights=self._incumbent_weights,
                robust_score=eval_metrics.score,
                eval_protocol_hash=eval_protocol_hash,
                windows_done=windows_done,
            )
        else:
            self._incumbent_score = best_pair_result.incumbent_metrics.score
            eval_metrics = best_pair_result.incumbent_metrics

        eval_metrics = replace(
            eval_metrics,
            elite_candidates_evaluated=len(challenger_indices),
            elite_selected_candidate_index=best_pair_result.candidate_index,
            elite_selection_reason=best_pair_result.selection_decision.reason,
            **self._window_search_fields(),
        )

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
        seed_anchor: int | None = None,
    ) -> WindowMetrics:
        request = _EvalRequest(
            ruleset_id=self._ruleset_id,
            seed=seed_anchor if seed_anchor is not None else self._seed_for(windows_done, candidate_index, phase_tag),
            strong_weights=candidate_weights,
            reference_weights=reference_weights,
            league_opponents=league_opponents,
            baseline_games=baseline_games,
            active_games=active_games,
        )
        return _evaluate_candidate_window(request)

    def _evaluate_paired(
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
        seed_anchor: int,
        incumbent_metrics: WindowMetrics | None = None,
    ) -> _PairedEvalResult:
        candidate_metrics = self._evaluate_one(
            windows_done=windows_done,
            candidate_index=candidate_index,
            candidate_weights=candidate_weights,
            reference_weights=reference_weights,
            league_opponents=league_opponents,
            baseline_games=baseline_games,
            active_games=active_games,
            phase_tag=phase_tag,
            seed_anchor=seed_anchor,
        )
        resolved_incumbent = incumbent_metrics
        if resolved_incumbent is None:
            resolved_incumbent = self._evaluate_one(
                windows_done=windows_done,
                candidate_index=candidate_index,
                candidate_weights=reference_weights,
                reference_weights=reference_weights,
                league_opponents=league_opponents,
                baseline_games=baseline_games,
                active_games=active_games,
                phase_tag=phase_tag,
                seed_anchor=seed_anchor,
            )
        candidate_metrics = replace(
            candidate_metrics,
            eval_seed_anchor=seed_anchor,
            incumbent_seed_anchor=seed_anchor,
            paired_eval=True,
            mirrored_first_player=True,
        )
        resolved_incumbent = replace(
            resolved_incumbent,
            eval_seed_anchor=seed_anchor,
            incumbent_seed_anchor=seed_anchor,
            paired_eval=True,
            mirrored_first_player=True,
        )
        decision = select_incumbent_lexicographic(
            candidate_metrics,
            resolved_incumbent,
            candidate_index=candidate_index,
        )
        candidate_metrics = replace(
            candidate_metrics,
            selection_robust_score_candidate=decision.robust_score_candidate,
            selection_robust_score_incumbent=decision.robust_score_incumbent,
            selection_robust_delta=decision.robust_delta,
            selection_noninferiority_passed=decision.noninferiority_passed,
            selection_attack_efficiency_candidate=decision.attack_efficiency_candidate,
            selection_attack_efficiency_incumbent=decision.attack_efficiency_incumbent,
            selection_attack_delta=decision.attack_delta,
            selection_tiebreak_used=decision.tiebreak_used,
            selection_decision_reason=decision.reason,
        )
        resolved_incumbent = replace(
            resolved_incumbent,
            selection_robust_score_candidate=decision.robust_score_candidate,
            selection_robust_score_incumbent=decision.robust_score_incumbent,
            selection_robust_delta=decision.robust_delta,
            selection_noninferiority_passed=decision.noninferiority_passed,
            selection_attack_efficiency_candidate=decision.attack_efficiency_candidate,
            selection_attack_efficiency_incumbent=decision.attack_efficiency_incumbent,
            selection_attack_delta=decision.attack_delta,
            selection_tiebreak_used=decision.tiebreak_used,
            selection_decision_reason=decision.reason,
        )
        return _PairedEvalResult(
            candidate_index=candidate_index,
            candidate_metrics=candidate_metrics,
            incumbent_metrics=resolved_incumbent,
            selection_decision=decision,
        )

    def search_observability(self) -> dict[str, float | int | str | bool]:
        return dict(self._window_search_fields())

    @classmethod
    def has_full_search_state(cls, snapshot: dict | None) -> bool:
        if not isinstance(snapshot, dict):
            return False
        required = {
            "search_policy",
            "cma_mean",
            "cma_sigma",
            "cma_diag",
            "cma_p_sigma",
            "cma_generation",
            "cma_parent_mu",
            "cma_mueff",
            "restart_count",
            "last_restart_reason",
            "last_restart_anchor_score",
            "last_restart_window",
            "anchor_insert_counter",
            "anchor_archive",
            "rng_state",
        }
        return required.issubset(snapshot.keys())

    def export_search_state(self) -> dict[str, object]:
        return {
            "search_policy": self._SEARCH_STATE_VERSION,
            "seed_base": int(self._seed),
            "population_size": int(self._population_size),
            "cma_mean": {key: float(self._cma_mean[key]) for key in self._param_names},
            "cma_sigma": float(self._cma_sigma),
            "cma_diag": {key: float(self._cma_diag[key]) for key in self._param_names},
            "cma_p_sigma": {key: float(self._cma_p_sigma[key]) for key in self._param_names},
            "cma_generation": int(self._cma_generation),
            "cma_parent_mu": int(self._last_cma_parent_mu),
            "cma_mueff": float(self._last_cma_mueff),
            "restart_count": int(self._restart_count),
            "last_restart_reason": self._last_restart_reason,
            "last_restart_anchor_score": float(self._last_restart_anchor_score),
            "last_restart_window": int(self._last_restart_window),
            "elite_fallback_used": bool(self._elite_fallback_used),
            "anchor_insert_counter": int(self._anchor_insert_counter),
            "anchor_archive": [
                {
                    "weights": dict(anchor.weights),
                    "robust_score": float(anchor.robust_score),
                    "eval_protocol_hash": anchor.eval_protocol_hash,
                    "windows_done": int(anchor.windows_done),
                    "insertion_index": int(anchor.insertion_index),
                }
                for anchor in self._anchor_archive
            ],
            "rng_state": base64.b64encode(pickle.dumps(self._rng.getstate())).decode("ascii"),
        }

    def restore_search_state(self, snapshot: dict) -> None:
        if not self.has_full_search_state(snapshot):
            raise ValueError("search_state snapshot is incomplete")
        if str(snapshot.get("search_policy")) != self._SEARCH_STATE_VERSION:
            raise ValueError("search_state policy mismatch")
        self._seed = int(snapshot.get("seed_base", self._seed))
        self._population_size = max(1, int(snapshot.get("population_size", self._population_size)))

        cma_mean = snapshot["cma_mean"]
        cma_diag = snapshot["cma_diag"]
        cma_p_sigma = snapshot["cma_p_sigma"]

        for key in self._param_names:
            if key not in cma_mean or key not in cma_diag or key not in cma_p_sigma:
                raise ValueError(f"search_state missing parameter '{key}'")

        self._cma_mean = {key: float(cma_mean[key]) for key in self._param_names}
        self._cma_sigma = self._clamp(float(snapshot["cma_sigma"]), self._CMA_SIGMA_MIN, self._CMA_SIGMA_MAX)
        self._cma_diag = {
            key: self._clamp(float(cma_diag[key]), self._CMA_DIAG_MIN, self._CMA_DIAG_MAX) for key in self._param_names
        }
        self._cma_p_sigma = {key: float(cma_p_sigma[key]) for key in self._param_names}
        self._cma_generation = max(0, int(snapshot["cma_generation"]))
        self._last_cma_parent_mu = max(0, int(snapshot["cma_parent_mu"]))
        self._last_cma_mueff = max(0.0, float(snapshot["cma_mueff"]))
        self._restart_count = max(0, int(snapshot["restart_count"]))
        self._last_restart_reason = str(snapshot["last_restart_reason"])
        self._last_restart_anchor_score = float(snapshot["last_restart_anchor_score"])
        self._last_restart_window = int(snapshot["last_restart_window"])
        self._elite_fallback_used = bool(snapshot.get("elite_fallback_used", False))
        self._anchor_insert_counter = max(0, int(snapshot["anchor_insert_counter"]))

        archive_payload = snapshot.get("anchor_archive", [])
        restored_archive: list[_RestartAnchor] = []
        for item in archive_payload:
            restored_archive.append(
                _RestartAnchor(
                    weights=normalize_weights(item.get("weights")),
                    robust_score=float(item.get("robust_score", 0.0)),
                    eval_protocol_hash=str(item.get("eval_protocol_hash", "")),
                    windows_done=int(item.get("windows_done", 0)),
                    insertion_index=int(item.get("insertion_index", 0)),
                )
            )
        restored_archive.sort(key=lambda anchor: (-anchor.robust_score, anchor.insertion_index))
        self._anchor_archive = restored_archive[: self._ANCHOR_ARCHIVE_LIMIT]

        rng_state_encoded = str(snapshot["rng_state"])
        rng_state = pickle.loads(base64.b64decode(rng_state_encoded.encode("ascii")))
        self._rng.setstate(rng_state)

    def _sample_challenger(self) -> dict[str, float]:
        sampled: dict[str, float] = {}
        for key in self._param_names:
            z = self._rng.gauss(0.0, 1.0)
            step = self._cma_sigma * math.sqrt(max(self._cma_diag[key], self._CMA_TINY)) * z
            raw = self._cma_mean[key] + step
            sampled[key] = round(self._clamp(raw, self._WEIGHT_MIN, self._WEIGHT_MAX), 6)
        return sampled

    def _update_cma_from_ranked_candidates(
        self,
        *,
        candidates: list[dict[str, float]],
        ranked_indices: list[int],
    ) -> None:
        challenger_indices = [idx for idx in ranked_indices if idx != 0]
        if not challenger_indices:
            self._last_cma_parent_mu = 0
            self._last_cma_mueff = 0.0
            return

        parent_mu = self._parent_mu_count()
        selected = challenger_indices[:parent_mu]
        if not selected:
            self._last_cma_parent_mu = 0
            self._last_cma_mueff = 0.0
            return

        parents = [normalize_weights(candidates[idx]) for idx in selected]
        weights, mueff = self._cma_recombination_weights(len(parents))

        old_mean = dict(self._cma_mean)
        old_diag = dict(self._cma_diag)
        old_sigma = max(self._cma_sigma, self._CMA_TINY)
        old_p_sigma = dict(self._cma_p_sigma)

        y_vectors: list[dict[str, float]] = []
        y_w = {key: 0.0 for key in self._param_names}
        for parent, weight in zip(parents, weights):
            y: dict[str, float] = {}
            for key in self._param_names:
                d_i = (parent[key] - old_mean[key]) / old_sigma
                y_i = d_i / math.sqrt(max(old_diag[key], self._CMA_TINY))
                y[key] = y_i
                y_w[key] += weight * y_i
            y_vectors.append(y)

        for key in self._param_names:
            step = old_sigma * math.sqrt(max(old_diag[key], self._CMA_TINY)) * y_w[key]
            self._cma_mean[key] = self._clamp(old_mean[key] + step, self._WEIGHT_MIN, self._WEIGHT_MAX)

        c_sigma = self._CMA_C_SIGMA
        coef = math.sqrt(c_sigma * (2.0 - c_sigma) * mueff)
        for key in self._param_names:
            self._cma_p_sigma[key] = (1.0 - c_sigma) * old_p_sigma[key] + coef * y_w[key]

        n = max(1, len(self._param_names))
        norm_p_sigma = math.sqrt(sum(self._cma_p_sigma[key] ** 2 for key in self._param_names))
        e_norm = math.sqrt(n) * (1.0 - 1.0 / (4.0 * n) + 1.0 / (21.0 * n * n))
        sigma_factor = math.exp((c_sigma / self._CMA_D_SIGMA) * (norm_p_sigma / max(e_norm, self._CMA_TINY) - 1.0))
        self._cma_sigma = self._clamp(
            old_sigma * sigma_factor,
            self._CMA_SIGMA_MIN,
            self._CMA_SIGMA_MAX,
        )

        c_cov = self._CMA_C_COV
        for key in self._param_names:
            diag_target = 0.0
            for weight, y in zip(weights, y_vectors):
                diag_target += weight * (y[key] * y[key])
            updated = (1.0 - c_cov) * old_diag[key] + c_cov * diag_target
            self._cma_diag[key] = self._clamp(updated, self._CMA_DIAG_MIN, self._CMA_DIAG_MAX)

        self._cma_generation += 1
        self._last_cma_parent_mu = len(parents)
        self._last_cma_mueff = mueff

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    def _parent_mu_count(self) -> int:
        lambda_count = max(0, self._population_size - 1)
        if lambda_count <= 0:
            return 0
        requested = max(2, lambda_count // 4)
        return max(1, min(lambda_count, requested))

    @staticmethod
    def _cma_recombination_weights(parent_mu: int) -> tuple[list[float], float]:
        raw = [math.log(parent_mu + 0.5) - math.log(rank) for rank in range(1, parent_mu + 1)]
        total = sum(raw)
        normalized = [value / total for value in raw]
        mueff = 1.0 / sum(weight * weight for weight in normalized)
        return normalized, mueff

    def _effective_sigma_values(self) -> list[float]:
        return [
            self._cma_sigma * math.sqrt(max(self._cma_diag[key], self._CMA_TINY))
            for key in self._param_names
        ]

    def _sigma_mean(self) -> float:
        values = self._effective_sigma_values()
        return round(sum(values) / max(1, len(values)), 6)

    def _sigma_min(self) -> float:
        values = self._effective_sigma_values()
        return round(min(values), 6) if values else 0.0

    def _sigma_max(self) -> float:
        values = self._effective_sigma_values()
        return round(max(values), 6) if values else 0.0

    def _cma_diag_mean(self) -> float:
        if not self._param_names:
            return 0.0
        return round(sum(self._cma_diag[key] for key in self._param_names) / len(self._param_names), 6)

    def _cma_diag_min(self) -> float:
        if not self._param_names:
            return 0.0
        return round(min(self._cma_diag[key] for key in self._param_names), 6)

    def _cma_diag_max(self) -> float:
        if not self._param_names:
            return 0.0
        return round(max(self._cma_diag[key] for key in self._param_names), 6)

    def _cma_mean_incumbent_l2(self) -> float:
        if not self._param_names:
            return 0.0
        squared = 0.0
        for key in self._param_names:
            delta = self._cma_mean[key] - self._incumbent_weights[key]
            squared += delta * delta
        return round(math.sqrt(squared), 6)

    def _window_search_fields(self) -> dict[str, float | int | str | bool]:
        return {
            "sigma_mean": self._sigma_mean(),
            "sigma_min": self._sigma_min(),
            "sigma_max": self._sigma_max(),
            "search_policy": self._SEARCH_POLICY,
            "cma_sigma": round(self._cma_sigma, 6),
            "cma_diag_mean": self._cma_diag_mean(),
            "cma_diag_min": self._cma_diag_min(),
            "cma_diag_max": self._cma_diag_max(),
            "cma_generation": self._cma_generation,
            "cma_mean_incumbent_l2": self._cma_mean_incumbent_l2(),
            "cma_parent_mu": self._last_cma_parent_mu,
            "cma_mueff": round(self._last_cma_mueff, 6),
            "restart_count": self._restart_count,
            "last_restart_reason": self._last_restart_reason,
            "last_restart_anchor_score": round(self._last_restart_anchor_score, 6),
            "last_restart_window": self._last_restart_window,
            "elite_fallback_used": self._elite_fallback_used,
        }

    def _record_anchor(
        self,
        *,
        weights: dict[str, float],
        robust_score: float,
        eval_protocol_hash: str,
        windows_done: int,
    ) -> None:
        self._anchor_insert_counter += 1
        self._anchor_archive.append(
            _RestartAnchor(
                weights=dict(normalize_weights(weights)),
                robust_score=float(robust_score),
                eval_protocol_hash=eval_protocol_hash,
                windows_done=windows_done,
                insertion_index=self._anchor_insert_counter,
            )
        )
        self._anchor_archive.sort(
            key=lambda item: (-item.robust_score, item.insertion_index),
        )
        self._anchor_archive = self._anchor_archive[: self._ANCHOR_ARCHIVE_LIMIT]

    def _has_anchor_for_protocol(self, eval_protocol_hash: str) -> bool:
        return any(anchor.eval_protocol_hash == eval_protocol_hash for anchor in self._anchor_archive)

    def _select_restart_anchor(self, *, eval_protocol_hash: str) -> _RestartAnchor | None:
        anchors = [item for item in self._anchor_archive if item.eval_protocol_hash == eval_protocol_hash]
        if not anchors:
            return None
        anchors.sort(key=lambda item: (-item.robust_score, item.insertion_index))
        return anchors[0]

    def _seed_for(self, windows_done: int, candidate_index: int, phase_tag: int) -> int:
        return (
            self._seed * 1_000_003
            + (windows_done + 1) * 100_003
            + candidate_index * 977
            + phase_tag * 10_007
        )
