from app.bots.policy import normalize_weights
from app.bots.selfplay import SelfPlaySimulator


def _clip_expected(key: str, value: float) -> float:
    del key
    return round(max(0.0, min(3.0, value)), 6)


def test_cma_sampling_uses_mean_sigma_and_diag() -> None:
    simulator = SelfPlaySimulator(
        ruleset_id="classic_v1",
        seed=123,
        window_games=16,
        population_size=6,
        train_split=0.7,
        worker_count=1,
    )
    base = normalize_weights(None)

    simulator._cma_mean = dict(base)
    simulator._cma_sigma = 0.0
    simulator._cma_diag = {key: 1.0 for key in base}
    sample = simulator._sample_challenger()
    assert sample == {key: _clip_expected(key, value) for key, value in base.items()}

    simulator._cma_sigma = 0.25
    simulator._cma_diag = {key: 0.05 for key in base}
    simulator._cma_diag["hunt_heat"] = 4.0

    heat_deltas: list[float] = []
    parity_deltas: list[float] = []
    for _ in range(400):
        mutated = simulator._sample_challenger()
        heat_deltas.append(abs(mutated["hunt_heat"] - base["hunt_heat"]))
        parity_deltas.append(abs(mutated["hunt_parity"] - base["hunt_parity"]))

    assert (sum(heat_deltas) / len(heat_deltas)) > (sum(parity_deltas) / len(parity_deltas)) * 3.0


def test_cma_update_is_deterministic_for_fixed_candidates() -> None:
    simulator_a = SelfPlaySimulator(
        ruleset_id="classic_v1",
        seed=7,
        window_games=16,
        population_size=8,
        train_split=0.7,
        worker_count=1,
    )
    simulator_b = SelfPlaySimulator(
        ruleset_id="classic_v1",
        seed=7,
        window_games=16,
        population_size=8,
        train_split=0.7,
        worker_count=1,
    )
    base = normalize_weights(None)
    candidates = [dict(base)]
    for delta in (0.15, 0.11, 0.07, -0.05, -0.09, 0.03, -0.02):
        candidate = {
            key: _clip_expected(key, value + (delta if key == "hunt_heat" else delta * 0.5))
            for key, value in base.items()
        }
        candidates.append(candidate)
    ranked = [3, 2, 1, 4, 5, 6, 7, 0]

    simulator_a._update_cma_from_ranked_candidates(candidates=candidates, ranked_indices=ranked)
    simulator_b._update_cma_from_ranked_candidates(candidates=candidates, ranked_indices=ranked)

    assert simulator_a._cma_mean == simulator_b._cma_mean
    assert simulator_a._cma_diag == simulator_b._cma_diag
    assert simulator_a._cma_p_sigma == simulator_b._cma_p_sigma
    assert simulator_a._cma_sigma == simulator_b._cma_sigma
    assert simulator_a._cma_generation == 1
    assert simulator_b._cma_generation == 1
    assert simulator_a.search_observability() == simulator_b.search_observability()


def test_cma_restart_reanchors_state_deterministically() -> None:
    simulator_a = SelfPlaySimulator(
        ruleset_id="classic_v1",
        seed=17,
        window_games=16,
        population_size=10,
        train_split=0.7,
        worker_count=1,
    )
    simulator_b = SelfPlaySimulator(
        ruleset_id="classic_v1",
        seed=17,
        window_games=16,
        population_size=10,
        train_split=0.7,
        worker_count=1,
    )

    for window in range(3):
        simulator_a.next_window(window, eval_protocol_hash="protocol-cma", league_opponents=[])
        simulator_b.next_window(window, eval_protocol_hash="protocol-cma", league_opponents=[])

    applied_a = simulator_a.maybe_restart(
        plateau_windows=20,
        restart_trigger_plateau_windows=8,
        eval_protocol_hash="protocol-cma",
        windows_done=12,
    )
    applied_b = simulator_b.maybe_restart(
        plateau_windows=20,
        restart_trigger_plateau_windows=8,
        eval_protocol_hash="protocol-cma",
        windows_done=12,
    )
    assert applied_a is True
    assert applied_b is True
    assert simulator_a.current_weights == simulator_b.current_weights
    assert simulator_a._cma_mean == simulator_b._cma_mean
    assert simulator_a._cma_generation == 0
    assert simulator_b._cma_generation == 0

    state = simulator_a.search_observability()
    assert state["search_policy"] == "sep_cma_es_lite_v1"
    assert state["restart_count"] == 1
    assert state["last_restart_reason"] == "plateau_restart"
    assert state["last_restart_window"] == 12
    assert state["cma_diag_min"] == 1.0
    assert state["cma_diag_max"] == 1.0
    assert state["cma_parent_mu"] == 0


def test_sigma_derived_fields_and_cma_observability_are_updated() -> None:
    simulator = SelfPlaySimulator(
        ruleset_id="classic_v1",
        seed=99,
        window_games=16,
        population_size=8,
        train_split=0.7,
        worker_count=1,
    )

    metrics = []
    for window in range(4):
        metrics.append(simulator.next_window(window, eval_protocol_hash="protocol-v2", league_opponents=[]))

    state = simulator.search_observability()
    assert state["cma_generation"] > 0
    assert 0.02 <= state["sigma_min"] <= state["sigma_mean"] <= state["sigma_max"] <= 0.45
    assert state["cma_sigma"] >= 0.02
    assert state["cma_diag_min"] >= 0.05
    assert state["cma_diag_max"] <= 4.0
    assert any(item.cma_generation > 0 for item in metrics)


def test_export_import_search_state_keeps_trajectory() -> None:
    full = SelfPlaySimulator(
        ruleset_id="classic_v1",
        seed=314,
        window_games=16,
        population_size=8,
        train_split=0.7,
        worker_count=1,
    )
    full_metrics = [full.next_window(window, eval_protocol_hash="protocol-j", league_opponents=[]) for window in range(6)]

    split = SelfPlaySimulator(
        ruleset_id="classic_v1",
        seed=314,
        window_games=16,
        population_size=8,
        train_split=0.7,
        worker_count=1,
    )
    for window in range(3):
        split.next_window(window, eval_protocol_hash="protocol-j", league_opponents=[])

    snapshot = split.export_search_state()
    restored = SelfPlaySimulator(
        ruleset_id="classic_v1",
        seed=314,
        window_games=16,
        population_size=8,
        train_split=0.7,
        worker_count=1,
        seed_weights=split.current_weights,
        seed_best_weights=split.best_weights,
        seed_best_score=split._best_score,
        search_state=snapshot,
    )

    restored_metrics = []
    for window in range(3, 6):
        restored_metrics.append(restored.next_window(window, eval_protocol_hash="protocol-j", league_opponents=[]))

    assert restored.current_weights == full.current_weights
    assert restored.best_weights == full.best_weights
    assert restored.search_observability() == full.search_observability()
    for idx, metric in enumerate(restored_metrics, start=3):
        assert metric.score == full_metrics[idx].score
        assert metric.selection_decision_reason == full_metrics[idx].selection_decision_reason
