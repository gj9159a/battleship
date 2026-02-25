from app.trainer.simulation import WindowMetrics, challenger_is_better, select_incumbent_lexicographic


def _metrics(
    *,
    lcb_random: float,
    lcb_strong: float,
    lcb_active: float,
    avg_shots_to_sink_all: float,
    p95_shots_to_sink_all: float,
    avg_shots_to_first_hit: float,
    avg_shots_after_first_hit_to_sink_all: float,
    score: float | None = None,
) -> WindowMetrics:
    robust = min(lcb_random, lcb_strong, lcb_active) if score is None else score
    return WindowMetrics(
        wr_baseline=0.0,
        wr_active=0.0,
        avg_turns_win=0.0,
        score=robust,
        avg_shots_to_sink_all=avg_shots_to_sink_all,
        p95_shots_to_sink_all=p95_shots_to_sink_all,
        avg_shots_to_first_hit=avg_shots_to_first_hit,
        avg_shots_after_first_hit_to_sink_all=avg_shots_after_first_hit_to_sink_all,
        lcb_random=lcb_random,
        lcb_strong=lcb_strong,
        lcb_active=lcb_active,
    )


def test_primary_guardrail_prefers_robust_even_with_worse_attack() -> None:
    incumbent = _metrics(
        lcb_random=0.50,
        lcb_strong=0.50,
        lcb_active=0.50,
        avg_shots_to_sink_all=28.0,
        p95_shots_to_sink_all=45.0,
        avg_shots_to_first_hit=5.0,
        avg_shots_after_first_hit_to_sink_all=23.0,
    )
    candidate = _metrics(
        lcb_random=0.505,
        lcb_strong=0.505,
        lcb_active=0.505,
        avg_shots_to_sink_all=36.0,
        p95_shots_to_sink_all=58.0,
        avg_shots_to_first_hit=7.0,
        avg_shots_after_first_hit_to_sink_all=29.0,
    )

    decision = select_incumbent_lexicographic(candidate, incumbent, candidate_index=5)
    assert decision.select_candidate is True
    assert decision.reason == "primary_better"


def test_primary_guardrail_blocks_weaker_robust_even_with_better_attack() -> None:
    incumbent = _metrics(
        lcb_random=0.51,
        lcb_strong=0.51,
        lcb_active=0.51,
        avg_shots_to_sink_all=36.0,
        p95_shots_to_sink_all=58.0,
        avg_shots_to_first_hit=7.0,
        avg_shots_after_first_hit_to_sink_all=29.0,
    )
    candidate = _metrics(
        lcb_random=0.507,
        lcb_strong=0.507,
        lcb_active=0.507,
        avg_shots_to_sink_all=27.0,
        p95_shots_to_sink_all=44.0,
        avg_shots_to_first_hit=5.0,
        avg_shots_after_first_hit_to_sink_all=22.0,
    )

    decision = select_incumbent_lexicographic(candidate, incumbent, candidate_index=3)
    assert decision.select_candidate is False
    assert decision.reason == "primary_worse"


def test_tiebreak_uses_attack_efficiency_when_robust_close_and_noninferior() -> None:
    incumbent = _metrics(
        lcb_random=0.500,
        lcb_strong=0.500,
        lcb_active=0.500,
        avg_shots_to_sink_all=30.0,
        p95_shots_to_sink_all=48.0,
        avg_shots_to_first_hit=6.0,
        avg_shots_after_first_hit_to_sink_all=24.0,
    )
    candidate = _metrics(
        lcb_random=0.499,
        lcb_strong=0.499,
        lcb_active=0.499,
        avg_shots_to_sink_all=28.0,
        p95_shots_to_sink_all=44.0,
        avg_shots_to_first_hit=5.0,
        avg_shots_after_first_hit_to_sink_all=22.0,
        score=0.5005,
    )

    decision = select_incumbent_lexicographic(candidate, incumbent, candidate_index=2)
    assert decision.select_candidate is True
    assert decision.tiebreak_used is True
    assert decision.noninferiority_passed is True
    assert decision.reason == "tiebreak_attack_better"


def test_noninferiority_blocks_attack_tiebreak() -> None:
    incumbent = _metrics(
        lcb_random=0.500,
        lcb_strong=0.500,
        lcb_active=0.500,
        avg_shots_to_sink_all=30.0,
        p95_shots_to_sink_all=48.0,
        avg_shots_to_first_hit=6.0,
        avg_shots_after_first_hit_to_sink_all=24.0,
    )
    candidate = _metrics(
        lcb_random=0.499,
        lcb_strong=0.499,
        lcb_active=0.494,
        avg_shots_to_sink_all=27.0,
        p95_shots_to_sink_all=43.0,
        avg_shots_to_first_hit=5.0,
        avg_shots_after_first_hit_to_sink_all=21.0,
        score=0.5004,
    )

    decision = select_incumbent_lexicographic(candidate, incumbent, candidate_index=1)
    assert decision.select_candidate is False
    assert decision.tiebreak_used is True
    assert decision.noninferiority_passed is False
    assert decision.reason == "tiebreak_blocked_noninferiority"


def test_selection_decision_is_deterministic_and_stable_on_exact_tie() -> None:
    incumbent = _metrics(
        lcb_random=0.500,
        lcb_strong=0.500,
        lcb_active=0.500,
        avg_shots_to_sink_all=30.0,
        p95_shots_to_sink_all=48.0,
        avg_shots_to_first_hit=6.0,
        avg_shots_after_first_hit_to_sink_all=24.0,
    )
    candidate = _metrics(
        lcb_random=0.500,
        lcb_strong=0.500,
        lcb_active=0.500,
        avg_shots_to_sink_all=30.0,
        p95_shots_to_sink_all=48.0,
        avg_shots_to_first_hit=6.0,
        avg_shots_after_first_hit_to_sink_all=24.0,
    )

    first = select_incumbent_lexicographic(candidate, incumbent, candidate_index=4)
    second = select_incumbent_lexicographic(candidate, incumbent, candidate_index=4)
    assert first == second
    assert first.select_candidate is False
    assert first.reason == "exact_tie_stable_order"


def test_elite_selection_uses_full_policy_not_proxy_top() -> None:
    incumbent = _metrics(
        lcb_random=0.500,
        lcb_strong=0.500,
        lcb_active=0.500,
        avg_shots_to_sink_all=30.0,
        p95_shots_to_sink_all=48.0,
        avg_shots_to_first_hit=6.0,
        avg_shots_after_first_hit_to_sink_all=24.0,
    )
    proxy_top_a = _metrics(
        lcb_random=0.501,
        lcb_strong=0.501,
        lcb_active=0.495,
        avg_shots_to_sink_all=27.0,
        p95_shots_to_sink_all=44.0,
        avg_shots_to_first_hit=5.0,
        avg_shots_after_first_hit_to_sink_all=21.0,
        score=0.5009,
    )
    challenger_b = _metrics(
        lcb_random=0.500,
        lcb_strong=0.500,
        lcb_active=0.500,
        avg_shots_to_sink_all=26.0,
        p95_shots_to_sink_all=41.0,
        avg_shots_to_first_hit=5.0,
        avg_shots_after_first_hit_to_sink_all=20.0,
        score=0.5004,
    )

    decision_a = select_incumbent_lexicographic(proxy_top_a, incumbent, candidate_index=1)
    decision_b = select_incumbent_lexicographic(challenger_b, incumbent, candidate_index=2)

    assert decision_a.select_candidate is False
    assert decision_a.reason == "tiebreak_blocked_noninferiority"
    assert decision_b.select_candidate is True
    assert decision_b.reason == "tiebreak_attack_better"
    assert challenger_is_better(decision_b, left_index=2, right=decision_a, right_index=1) is True


def test_elite_selection_order_invariance() -> None:
    incumbent = _metrics(
        lcb_random=0.500,
        lcb_strong=0.500,
        lcb_active=0.500,
        avg_shots_to_sink_all=30.0,
        p95_shots_to_sink_all=48.0,
        avg_shots_to_first_hit=6.0,
        avg_shots_after_first_hit_to_sink_all=24.0,
    )
    candidates = {
        1: _metrics(
            lcb_random=0.499,
            lcb_strong=0.499,
            lcb_active=0.499,
            avg_shots_to_sink_all=28.0,
            p95_shots_to_sink_all=44.0,
            avg_shots_to_first_hit=5.0,
            avg_shots_after_first_hit_to_sink_all=22.0,
            score=0.5005,
        ),
        2: _metrics(
            lcb_random=0.501,
            lcb_strong=0.501,
            lcb_active=0.501,
            avg_shots_to_sink_all=29.0,
            p95_shots_to_sink_all=46.0,
            avg_shots_to_first_hit=6.0,
            avg_shots_after_first_hit_to_sink_all=23.0,
            score=0.5035,
        ),
        3: _metrics(
            lcb_random=0.499,
            lcb_strong=0.499,
            lcb_active=0.497,
            avg_shots_to_sink_all=27.0,
            p95_shots_to_sink_all=43.0,
            avg_shots_to_first_hit=5.0,
            avg_shots_after_first_hit_to_sink_all=21.0,
            score=0.5006,
        ),
    }

    def pick(order: list[int]) -> int:
        best_idx = order[0]
        best_decision = select_incumbent_lexicographic(candidates[best_idx], incumbent, candidate_index=best_idx)
        for idx in order[1:]:
            decision = select_incumbent_lexicographic(candidates[idx], incumbent, candidate_index=idx)
            if challenger_is_better(decision, left_index=idx, right=best_decision, right_index=best_idx):
                best_idx = idx
                best_decision = decision
        return best_idx

    assert pick([1, 2, 3]) == 2
    assert pick([3, 1, 2]) == 2
    assert pick([2, 3, 1]) == 2


def test_elite_selection_exact_tie_prefers_stable_index() -> None:
    incumbent = _metrics(
        lcb_random=0.500,
        lcb_strong=0.500,
        lcb_active=0.500,
        avg_shots_to_sink_all=30.0,
        p95_shots_to_sink_all=48.0,
        avg_shots_to_first_hit=6.0,
        avg_shots_after_first_hit_to_sink_all=24.0,
    )
    tied = _metrics(
        lcb_random=0.500,
        lcb_strong=0.500,
        lcb_active=0.500,
        avg_shots_to_sink_all=30.0,
        p95_shots_to_sink_all=48.0,
        avg_shots_to_first_hit=6.0,
        avg_shots_after_first_hit_to_sink_all=24.0,
    )

    decision_2 = select_incumbent_lexicographic(tied, incumbent, candidate_index=2)
    decision_3 = select_incumbent_lexicographic(tied, incumbent, candidate_index=3)
    assert challenger_is_better(decision_2, left_index=2, right=decision_3, right_index=3) is True
