from dataclasses import replace
from pathlib import Path

from app.bots.models import BotVersion
from app.services import BotCatalogService, FrozenBenchmarkService
from app.storage import SQLiteStore


def _bootstrap_services(tmp_path: Path):
    store = SQLiteStore(tmp_path / "app.sqlite3")
    catalog = BotCatalogService(store=store)
    catalog.ensure_bot(
        bot_version_id="classic_v1-baseline-strong",
        ruleset_id="classic_v1",
        policy_type="probability_strong",
        feature_schema_version="classic_features_v1",
        lookahead_policy_version="adaptive_v1",
        weights={"hunt_heat": 1.0, "target_adjacent": 1.0},
        tags={"baseline"},
    )
    catalog.ensure_bot(
        bot_version_id="candidate-eval",
        ruleset_id="classic_v1",
        policy_type="probability_strong",
        feature_schema_version="classic_features_v1",
        lookahead_policy_version="adaptive_v1",
        weights={"hunt_heat": 1.1, "target_adjacent": 0.95},
        tags={"active"},
    )
    service = FrozenBenchmarkService(store=store, bot_catalog=catalog)
    suites = service.ensure_frozen_suites("classic_v1", suite_tier="canonical")
    return store, catalog, service, suites


def test_frozen_suite_run_is_deterministic(tmp_path: Path) -> None:
    _, _, service, suites = _bootstrap_services(tmp_path)
    random_suite = suites["random"]
    assert random_suite.suite_tier == "canonical"

    run_a = service.run_suite_for_bot_version(random_suite.suite_id, "candidate-eval")
    run_b = service.run_suite_for_bot_version(random_suite.suite_id, "candidate-eval")

    assert run_a.winrate == run_b.winrate
    assert run_a.lcb == run_b.lcb
    assert run_a.avg_shots_to_sink_all == run_b.avg_shots_to_sink_all
    assert run_a.p95_shots_to_sink_all == run_b.p95_shots_to_sink_all
    assert run_a.avg_shots_to_first_hit == run_b.avg_shots_to_first_hit


def test_frozen_suite_is_not_affected_by_new_pool_bots(tmp_path: Path) -> None:
    _, catalog, service, suites = _bootstrap_services(tmp_path)
    strong_suite = suites["strong"]

    first = service.run_suite_for_bot_version(strong_suite.suite_id, "candidate-eval")

    for idx in range(12):
        catalog.ensure_bot(
            bot_version_id=f"active-{idx}",
            ruleset_id="classic_v1",
            policy_type="probability_strong",
            feature_schema_version="classic_features_v1",
            lookahead_policy_version="adaptive_v1",
            weights={"hunt_heat": 0.8 + idx * 0.01, "target_adjacent": 1.1},
            tags={"active"},
        )

    second = service.run_suite_for_bot_version(strong_suite.suite_id, "candidate-eval")
    assert first.winrate == second.winrate
    assert first.lcb == second.lcb


def test_frozen_strong_suite_uses_snapshot_weights(tmp_path: Path) -> None:
    _, catalog, service, suites = _bootstrap_services(tmp_path)
    strong_suite = suites["strong"]
    before = service.run_suite_for_bot_version(strong_suite.suite_id, "candidate-eval")

    baseline = catalog.get_bot("classic_v1-baseline-strong")
    catalog._bots["classic_v1-baseline-strong"] = replace(  # type: ignore[attr-defined]
        baseline,
        weights={"hunt_heat": 2.4, "target_adjacent": 2.4, "target_line": 2.4},
    )

    after = service.run_suite_for_bot_version(strong_suite.suite_id, "candidate-eval")
    assert before.winrate == after.winrate
    assert before.lcb == after.lcb
    assert strong_suite.opponent_bot_version_id == "classic_v1-baseline-strong"
    assert strong_suite.opponent_weights["hunt_heat"] != 2.4


def test_ci_smoke_tier_is_separated_from_canonical(tmp_path: Path) -> None:
    _, _, service, canonical = _bootstrap_services(tmp_path)
    ci_smoke = service.ensure_frozen_suites("classic_v1", suite_tier="ci_smoke")

    assert canonical["random"].suite_tier == "canonical"
    assert ci_smoke["random"].suite_tier == "ci_smoke"
    assert canonical["random"].suite_id != ci_smoke["random"].suite_id
    assert canonical["strong"].suite_id != ci_smoke["strong"].suite_id


def test_default_checkpoint_suites_use_only_canonical(tmp_path: Path) -> None:
    _, _, service, canonical = _bootstrap_services(tmp_path)
    ci_smoke = service.ensure_frozen_suites("classic_v1", suite_tier="ci_smoke")

    summaries = service.run_default_suites_for_checkpoint(
        ruleset_id="classic_v1",
        checkpoint_id="cp-1",
        weights={"hunt_heat": 1.05, "target_adjacent": 1.02},
    )

    assert set(summaries.keys()) == {"random", "strong"}
    for summary in summaries.values():
        assert summary["suite_tier"] == "canonical"

    assert len(service.list_suite_runs(canonical["random"].suite_id)) == 1
    assert len(service.list_suite_runs(canonical["strong"].suite_id)) == 1
    assert not service.list_suite_runs(ci_smoke["random"].suite_id)
    assert not service.list_suite_runs(ci_smoke["strong"].suite_id)
