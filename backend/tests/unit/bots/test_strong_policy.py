import random

from app.bots.policy import StrongBotConfig, StrongBotPolicy
from app.bots.selfplay import SelfPlaySimulator
from app.rulesets.catalog import CLASSIC_V1
from app.trainer.simulation import WindowMetrics


def test_strong_bot_policy_never_repeats_shot() -> None:
    bot = StrongBotPolicy(CLASSIC_V1, rng=random.Random(123))

    seen = set()
    for _ in range(80):
        shot = bot.select_shot()
        assert shot not in seen
        seen.add(shot)
        bot.observe_shot(shot, "miss")


def test_strong_bot_policy_is_deterministic_for_same_seed() -> None:
    b1 = StrongBotPolicy(CLASSIC_V1, rng=random.Random(2026))
    b2 = StrongBotPolicy(CLASSIC_V1, rng=random.Random(2026))

    seq1 = []
    seq2 = []
    outcomes = ["miss", "hit", "miss", "hit", "sunk"] * 8
    for outcome in outcomes:
        shot1 = b1.select_shot()
        shot2 = b2.select_shot()
        seq1.append(shot1)
        seq2.append(shot2)
        b1.observe_shot(shot1, outcome)
        b2.observe_shot(shot2, outcome)

    assert seq1 == seq2


def test_self_play_simulator_is_deterministic() -> None:
    s1 = SelfPlaySimulator(
        ruleset_id="classic_v1",
        seed=77,
        window_games=4,
        population_size=4,
        train_split=0.6,
        worker_count=1,
    )
    s2 = SelfPlaySimulator(
        ruleset_id="classic_v1",
        seed=77,
        window_games=4,
        population_size=4,
        train_split=0.6,
        worker_count=1,
    )

    seq1 = [s1.next_window(i, eval_protocol_hash="test-protocol").score for i in range(3)]
    seq2 = [s2.next_window(i, eval_protocol_hash="test-protocol").score for i in range(3)]

    assert seq1 == seq2
    assert s1.best_weights == s2.best_weights


def test_self_play_simulator_evaluates_only_top_ranked_challenger(monkeypatch) -> None:
    simulator = SelfPlaySimulator(
        ruleset_id="classic_v1",
        seed=77,
        window_games=8,
        population_size=32,
        train_split=0.6,
        worker_count=1,
    )

    def fake_population(self, **kwargs):
        candidates = kwargs["candidates"]
        return [
            WindowMetrics(wr_baseline=0.5, wr_active=0.5, avg_turns_win=40.0, score=float(index))
            for index, _ in enumerate(candidates)
        ]

    eval_indices: list[int] = []

    def fake_evaluate_one(self, **kwargs):
        candidate_index = int(kwargs["candidate_index"])
        eval_indices.append(candidate_index)
        return WindowMetrics(
            wr_baseline=0.6,
            wr_active=0.6,
            avg_turns_win=30.0,
            score=float(candidate_index),
        )

    monkeypatch.setattr(SelfPlaySimulator, "_evaluate_population", fake_population)
    monkeypatch.setattr(SelfPlaySimulator, "_evaluate_one", fake_evaluate_one)

    simulator.next_window(0, eval_protocol_hash="test-protocol")

    assert len(eval_indices) == 2
    assert eval_indices[0] == 0
    assert eval_indices[1] == 31


def test_self_play_simulator_eval_is_strict_paired(monkeypatch) -> None:
    simulator = SelfPlaySimulator(
        ruleset_id="classic_v1",
        seed=91,
        window_games=8,
        population_size=4,
        train_split=0.6,
        worker_count=1,
    )

    def fake_population(self, **kwargs):
        candidates = kwargs["candidates"]
        return [
            WindowMetrics(wr_baseline=0.5, wr_active=0.5, avg_turns_win=40.0, score=float(index))
            for index, _ in enumerate(candidates)
        ]

    calls: list[tuple[int, int | None, bool]] = []

    def fake_evaluate_one(self, **kwargs):
        candidate_index = int(kwargs["candidate_index"])
        seed_anchor = kwargs.get("seed_anchor")
        candidate_weights = kwargs["candidate_weights"]
        reference_weights = kwargs["reference_weights"]
        is_incumbent_eval = candidate_weights == reference_weights
        calls.append((candidate_index, seed_anchor, is_incumbent_eval))
        score = 0.62 if not is_incumbent_eval else 0.55
        return WindowMetrics(
            wr_baseline=0.6,
            wr_active=0.6,
            avg_turns_win=30.0,
            score=score,
            eval_seed_anchor=seed_anchor or 0,
        )

    monkeypatch.setattr(SelfPlaySimulator, "_evaluate_population", fake_population)
    monkeypatch.setattr(SelfPlaySimulator, "_evaluate_one", fake_evaluate_one)

    metrics = simulator.next_window(0, eval_protocol_hash="test-protocol")

    assert len(calls) == 2
    assert calls[0][1] is not None
    assert calls[0][1] == calls[1][1]
    assert {calls[0][2], calls[1][2]} == {True, False}
    assert metrics.paired_eval is True
    assert metrics.mirrored_first_player is True
    assert metrics.eval_seed_anchor == metrics.incumbent_seed_anchor


def test_self_play_simulator_reports_attack_efficiency_metrics() -> None:
    simulator = SelfPlaySimulator(
        ruleset_id="classic_v1",
        seed=55,
        window_games=4,
        population_size=1,
        train_split=0.5,
        worker_count=1,
    )

    metrics = simulator.next_window(0, eval_protocol_hash="test-protocol")

    assert metrics.avg_shots_to_sink_all > 0
    assert metrics.p95_shots_to_sink_all >= metrics.avg_shots_to_sink_all
    assert metrics.avg_shots_to_first_hit > 0
    assert metrics.avg_shots_after_first_hit_to_sink_all >= 0
    assert metrics.avg_misses_before_first_hit >= 0


def test_strong_bot_depth2_applies_only_top_k_neighbors(monkeypatch) -> None:
    bot = StrongBotPolicy(
        CLASSIC_V1,
        rng=random.Random(77),
        config=StrongBotConfig(lookahead_mode="depth2", lookahead_policy_version="adaptive_v1"),
    )

    calls = 0
    original = bot._neighbor_average_heat

    def wrapped(cell, heat):
        nonlocal calls
        calls += 1
        return original(cell, heat)

    monkeypatch.setattr(bot, "_neighbor_average_heat", wrapped)
    bot.select_shot()
    assert calls <= 12


def test_strong_bot_fast_target_mode_uses_line_frontier() -> None:
    bot = StrongBotPolicy(CLASSIC_V1, rng=random.Random(101))
    bot._fired = {(4, 4), (4, 5)}
    bot._hits_pending = {(4, 4), (4, 5)}

    available = [
        (row, col)
        for row in range(CLASSIC_V1.board_size)
        for col in range(CLASSIC_V1.board_size)
        if (row, col) not in bot._fired
    ]
    candidates = set(bot._candidate_cells(available, target_mode=True))
    assert candidates == {(4, 3), (4, 6)}
