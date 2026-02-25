import asyncio
from pathlib import Path

from app.services import BotCatalogService, EventBus, LeagueService, TrainingJobService
from app.storage import SQLiteStore
from app.trainer import TrainingParams


def test_bot_catalog_persists_versions(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "app.sqlite3")
    service = BotCatalogService(store=store)
    service.ensure_bot(
        bot_version_id="persist-bot-1",
        ruleset_id="classic_v1",
        policy_type="probability_strong",
        feature_schema_version="classic_features_v1",
        lookahead_policy_version="adaptive_v1",
        weights={"hunt_heat": 1.1, "target_adjacent": 0.9},
        tags={"active"},
    )

    restored = BotCatalogService(store=store)
    bot = restored.get_bot("persist-bot-1")
    assert bot.ruleset_id == "classic_v1"
    assert bot.policy_type == "probability_strong"
    assert "active" in bot.tags
    assert bot.weights["hunt_heat"] == 1.1


def test_league_persists_ratings_and_matches(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "app.sqlite3")
    catalog = BotCatalogService(store=store)
    for bot_id in ("persist-a", "persist-b"):
        catalog.ensure_bot(
            bot_version_id=bot_id,
            ruleset_id="classic_v1",
            policy_type="probability_strong",
            feature_schema_version="classic_features_v1",
            lookahead_policy_version="adaptive_v1",
            weights={"hunt_heat": 1.0, "target_adjacent": 1.0},
        )

    league = LeagueService(event_bus=EventBus(), store=store, bot_catalog=catalog)
    league.register_bot("classic_v1", "persist-a", "active")
    league.register_bot("classic_v1", "persist-b", "active")
    league.record_match(
        ruleset_id="classic_v1",
        bot_a_id="persist-a",
        bot_b_id="persist-b",
        winner_id="persist-a",
    )

    restored = LeagueService(event_bus=EventBus(), store=store, bot_catalog=catalog)
    table = {row.bot_version_id: row for row in restored.list_table("classic_v1")}
    assert table["persist-a"].matches_played == 1
    assert table["persist-b"].matches_played == 1
    matrix = restored.get_matchup_matrix("classic_v1")
    assert len(matrix) == 1
    assert matrix[0]["total"] == 1


def test_training_persists_jobs_and_checkpoints(tmp_path: Path) -> None:
    async def _scenario() -> None:
        store = SQLiteStore(tmp_path / "app.sqlite3")
        checkpoint_root = tmp_path / "checkpoints"
        service = TrainingJobService(
            event_bus=EventBus(),
            checkpoint_root=checkpoint_root,
            store=store,
        )
        job = service.create_job(
            ruleset_id="classic_v1",
            profile_id=None,
            seed=7,
            params=TrainingParams(
                microbatch_size=5,
                eval_window_batches=1,
                checkpoint_interval_batches=1,
                population_size=4,
                train_split=0.6,
                worker_count=1,
                quality_gate_games=20,
                target_score=1.0,
                early_stop_plateau_windows=100000,
                tick_delay_ms=1,
            ),
        )
        await service.apply_command(job.id, "start")

        checkpoints = []
        for _ in range(300):
            checkpoints = service.list_checkpoints(job.id)
            if checkpoints:
                break
            await asyncio.sleep(0.01)
        assert checkpoints

        await service.apply_command(job.id, "pause")
        for _ in range(300):
            if service.get_job(job.id).lifecycle_state == "Paused":
                break
            await asyncio.sleep(0.01)
        assert service.get_job(job.id).lifecycle_state == "Paused"

        restored = TrainingJobService(
            event_bus=EventBus(),
            checkpoint_root=checkpoint_root,
            store=store,
        )
        restored_job = restored.get_job(job.id)
        assert restored_job.lifecycle_state == "Paused"
        assert restored.list_checkpoints(job.id)

        await service.apply_command(job.id, "stop")

    asyncio.run(_scenario())
