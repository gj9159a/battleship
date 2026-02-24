import random

from app.bots.policy import StrongBotPolicy
from app.bots.selfplay import SelfPlaySimulator
from app.rulesets.catalog import CLASSIC_V1


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

    seq1 = [s1.next_window(i).score for i in range(3)]
    seq2 = [s2.next_window(i).score for i in range(3)]

    assert seq1 == seq2
    assert s1.best_weights == s2.best_weights
