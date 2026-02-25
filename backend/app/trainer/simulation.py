import math
import random
from dataclasses import dataclass

SELECTION_POLICY_VERSION = "robust_lcb_lexicographic_attack_v1"
ROBUST_EPSILON = 0.002
GROUP_NONINFERIORITY_EPSILON = 0.003
ATTACK_TIEBREAK_EPSILON = 0.001
ATTACK_RATIO_TINY = 1e-9
ATTACK_EFFICIENCY_WEIGHTS: dict[str, float] = {
    "avg_shots_to_sink_all": 0.45,
    "p95_shots_to_sink_all": 0.30,
    "avg_shots_to_first_hit": 0.15,
    "avg_shots_after_first_hit_to_sink_all": 0.10,
}


@dataclass(frozen=True, slots=True)
class WindowMetrics:
    wr_baseline: float
    wr_active: float
    avg_turns_win: float
    score: float
    avg_shots_to_sink_all: float = 0.0
    p95_shots_to_sink_all: float = 0.0
    avg_shots_to_first_hit: float = 0.0
    avg_shots_after_first_hit_to_sink_all: float = 0.0
    avg_misses_before_first_hit: float = 0.0
    eval_seed_anchor: int = 0
    incumbent_seed_anchor: int = 0
    paired_eval: bool = False
    mirrored_first_player: bool = True
    lcb_random: float = 0.0
    lcb_strong: float = 0.0
    lcb_active: float = 0.0
    selection_robust_score_candidate: float = 0.0
    selection_robust_score_incumbent: float = 0.0
    selection_robust_delta: float = 0.0
    selection_noninferiority_passed: bool = False
    selection_attack_efficiency_candidate: float = 0.0
    selection_attack_efficiency_incumbent: float = 0.0
    selection_attack_delta: float = 0.0
    selection_tiebreak_used: bool = False
    selection_decision_reason: str = "unknown"
    elite_candidates_evaluated: int = 0
    elite_selected_candidate_index: int = -1
    elite_selection_reason: str = "unknown"
    sigma_mean: float = 0.0
    sigma_min: float = 0.0
    sigma_max: float = 0.0
    search_policy: str = "sep_cma_es_lite_v1"
    cma_sigma: float = 0.0
    cma_diag_mean: float = 0.0
    cma_diag_min: float = 0.0
    cma_diag_max: float = 0.0
    cma_generation: int = 0
    cma_mean_incumbent_l2: float = 0.0
    cma_parent_mu: int = 0
    cma_mueff: float = 0.0
    restart_count: int = 0
    last_restart_reason: str = "none"
    last_restart_anchor_score: float = 0.0
    last_restart_window: int = -1
    elite_fallback_used: bool = False


@dataclass(frozen=True, slots=True)
class SelectionDecision:
    select_candidate: bool
    robust_score_candidate: float
    robust_score_incumbent: float
    robust_delta: float
    noninferiority_passed: bool
    attack_efficiency_candidate: float
    attack_efficiency_incumbent: float
    attack_delta: float
    tiebreak_used: bool
    reason: str


def selection_order_key(
    decision: SelectionDecision,
    *,
    candidate_index: int,
) -> tuple[float, float, float, float]:
    if decision.reason == "primary_better":
        return (4.0, decision.robust_score_candidate, -decision.attack_efficiency_candidate, -float(candidate_index))
    if decision.reason == "tiebreak_attack_better":
        return (3.0, -decision.attack_efficiency_candidate, decision.robust_score_candidate, -float(candidate_index))
    if decision.reason == "exact_tie_stable_order" and decision.select_candidate:
        return (2.0, 0.0, 0.0, -float(candidate_index))
    if decision.reason == "tiebreak_blocked_noninferiority":
        return (1.0, decision.robust_score_candidate, -decision.attack_efficiency_candidate, -float(candidate_index))
    if decision.reason == "tiebreak_attack_worse":
        return (0.0, -decision.attack_efficiency_candidate, decision.robust_score_candidate, -float(candidate_index))
    return (-1.0, decision.robust_score_candidate, -decision.attack_efficiency_candidate, -float(candidate_index))


def challenger_is_better(
    left: SelectionDecision,
    *,
    left_index: int,
    right: SelectionDecision,
    right_index: int,
) -> bool:
    return selection_order_key(left, candidate_index=left_index) > selection_order_key(right, candidate_index=right_index)


def compute_score(
    wr_baseline: float,
    wr_active: float,
    avg_turns_win: float,
    *,
    lcb_random: float | None = None,
    lcb_strong: float | None = None,
    lcb_active: float | None = None,
) -> float:
    del avg_turns_win
    if lcb_random is not None and lcb_strong is not None and lcb_active is not None:
        return min(lcb_random, lcb_strong, lcb_active)
    return min(wr_baseline, wr_active)


def attack_efficiency_score(
    candidate: WindowMetrics,
    incumbent: WindowMetrics,
    *,
    tiny: float = ATTACK_RATIO_TINY,
) -> float:
    cand_sink = candidate.avg_shots_to_sink_all / max(incumbent.avg_shots_to_sink_all, tiny)
    cand_p95 = candidate.p95_shots_to_sink_all / max(incumbent.p95_shots_to_sink_all, tiny)
    cand_first_hit = candidate.avg_shots_to_first_hit / max(incumbent.avg_shots_to_first_hit, tiny)
    cand_after_hit = (
        candidate.avg_shots_after_first_hit_to_sink_all
        / max(incumbent.avg_shots_after_first_hit_to_sink_all, tiny)
    )
    return (
        ATTACK_EFFICIENCY_WEIGHTS["avg_shots_to_sink_all"] * cand_sink
        + ATTACK_EFFICIENCY_WEIGHTS["p95_shots_to_sink_all"] * cand_p95
        + ATTACK_EFFICIENCY_WEIGHTS["avg_shots_to_first_hit"] * cand_first_hit
        + ATTACK_EFFICIENCY_WEIGHTS["avg_shots_after_first_hit_to_sink_all"] * cand_after_hit
    )


def select_incumbent_lexicographic(
    candidate: WindowMetrics,
    incumbent: WindowMetrics,
    *,
    candidate_index: int,
    robust_epsilon: float = ROBUST_EPSILON,
    group_noninferiority_epsilon: float = GROUP_NONINFERIORITY_EPSILON,
    attack_tiebreak_epsilon: float = ATTACK_TIEBREAK_EPSILON,
) -> SelectionDecision:
    candidate_robust = candidate.score
    incumbent_robust = incumbent.score
    robust_delta = candidate_robust - incumbent_robust
    candidate_attack = attack_efficiency_score(candidate, incumbent)
    incumbent_attack = attack_efficiency_score(incumbent, incumbent)
    attack_delta = candidate_attack - incumbent_attack

    if robust_delta > robust_epsilon:
        return SelectionDecision(
            select_candidate=True,
            robust_score_candidate=round(candidate_robust, 6),
            robust_score_incumbent=round(incumbent_robust, 6),
            robust_delta=round(robust_delta, 6),
            noninferiority_passed=True,
            attack_efficiency_candidate=round(candidate_attack, 6),
            attack_efficiency_incumbent=round(incumbent_attack, 6),
            attack_delta=round(attack_delta, 6),
            tiebreak_used=False,
            reason="primary_better",
        )

    if robust_delta < -robust_epsilon:
        return SelectionDecision(
            select_candidate=False,
            robust_score_candidate=round(candidate_robust, 6),
            robust_score_incumbent=round(incumbent_robust, 6),
            robust_delta=round(robust_delta, 6),
            noninferiority_passed=False,
            attack_efficiency_candidate=round(candidate_attack, 6),
            attack_efficiency_incumbent=round(incumbent_attack, 6),
            attack_delta=round(attack_delta, 6),
            tiebreak_used=False,
            reason="primary_worse",
        )

    noninferiority_passed = (
        candidate.lcb_random >= incumbent.lcb_random - group_noninferiority_epsilon
        and candidate.lcb_strong >= incumbent.lcb_strong - group_noninferiority_epsilon
        and candidate.lcb_active >= incumbent.lcb_active - group_noninferiority_epsilon
    )
    if not noninferiority_passed:
        return SelectionDecision(
            select_candidate=False,
            robust_score_candidate=round(candidate_robust, 6),
            robust_score_incumbent=round(incumbent_robust, 6),
            robust_delta=round(robust_delta, 6),
            noninferiority_passed=False,
            attack_efficiency_candidate=round(candidate_attack, 6),
            attack_efficiency_incumbent=round(incumbent_attack, 6),
            attack_delta=round(attack_delta, 6),
            tiebreak_used=True,
            reason="tiebreak_blocked_noninferiority",
        )

    if attack_delta < -attack_tiebreak_epsilon:
        return SelectionDecision(
            select_candidate=True,
            robust_score_candidate=round(candidate_robust, 6),
            robust_score_incumbent=round(incumbent_robust, 6),
            robust_delta=round(robust_delta, 6),
            noninferiority_passed=True,
            attack_efficiency_candidate=round(candidate_attack, 6),
            attack_efficiency_incumbent=round(incumbent_attack, 6),
            attack_delta=round(attack_delta, 6),
            tiebreak_used=True,
            reason="tiebreak_attack_better",
        )

    if attack_delta > attack_tiebreak_epsilon:
        return SelectionDecision(
            select_candidate=False,
            robust_score_candidate=round(candidate_robust, 6),
            robust_score_incumbent=round(incumbent_robust, 6),
            robust_delta=round(robust_delta, 6),
            noninferiority_passed=True,
            attack_efficiency_candidate=round(candidate_attack, 6),
            attack_efficiency_incumbent=round(incumbent_attack, 6),
            attack_delta=round(attack_delta, 6),
            tiebreak_used=True,
            reason="tiebreak_attack_worse",
        )

    select_candidate = candidate_index <= 0
    return SelectionDecision(
        select_candidate=select_candidate,
        robust_score_candidate=round(candidate_robust, 6),
        robust_score_incumbent=round(incumbent_robust, 6),
        robust_delta=round(robust_delta, 6),
        noninferiority_passed=True,
        attack_efficiency_candidate=round(candidate_attack, 6),
        attack_efficiency_incumbent=round(incumbent_attack, 6),
        attack_delta=round(attack_delta, 6),
        tiebreak_used=True,
        reason="exact_tie_stable_order",
    )


class DeterministicSimulator:
    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def next_window(self, windows_done: int) -> WindowMetrics:
        # Smooth saturating curve to make plateau detection testable.
        trend = 0.38 + 0.40 * (1 - math.exp(-(windows_done + 1) / 6.0))
        wr_baseline = min(0.97, max(0.05, trend + self._rng.uniform(-0.01, 0.01)))
        wr_active = min(0.95, max(0.05, trend - 0.05 + self._rng.uniform(-0.015, 0.015)))
        avg_turns_win = max(20.0, 68.0 - windows_done * 0.9 + self._rng.uniform(-1.2, 1.2))
        score = compute_score(wr_baseline, wr_active, avg_turns_win)
        return WindowMetrics(
            wr_baseline=round(wr_baseline, 6),
            wr_active=round(wr_active, 6),
            avg_turns_win=round(avg_turns_win, 6),
            score=round(score, 6),
        )
