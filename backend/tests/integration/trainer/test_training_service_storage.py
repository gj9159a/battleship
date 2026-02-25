import asyncio
import time
from pathlib import Path

from app.bots.selfplay import SelfPlaySimulator
from app.services import EventBus
from app.services.training_jobs import TrainingJobService
from app.storage import SQLiteStore
from app.trainer import TrainingParams


def _fast_params() -> TrainingParams:
    return TrainingParams(
        microbatch_size=2,
        eval_window_batches=1,
        checkpoint_interval_batches=1,
        population_size=2,
        train_split=0.6,
        worker_count=1,
        quality_gate_games=4,
        target_score=1.0,
        early_stop_plateau_windows=100000,
        tick_delay_ms=0,
    )


def test_training_service_checkpoint_interface_is_disabled(tmp_path: Path) -> None:
    service = TrainingJobService(
        event_bus=EventBus(),
        checkpoint_root=tmp_path / "training_checkpoints",
    )
    job = service.create_job(
        ruleset_id="classic_v1",
        profile_id=None,
        seed=5,
        params=_fast_params(),
    )

    assert service.list_checkpoints(job.id) == []
    assert service.list_all_checkpoints() == []

    try:
        service.get_checkpoint_payload(job.id, "disabled")
    except KeyError as exc:
        assert "disabled" in str(exc).lower()
    else:
        raise AssertionError("expected checkpoint payload API to be disabled")

    try:
        asyncio.run(service.load_checkpoint(job.id, "disabled"))
    except ValueError as exc:
        assert "disabled" in str(exc).lower()
    else:
        raise AssertionError("expected checkpoint load API to be disabled")


def test_training_runs_with_delayed_eval_and_never_creates_checkpoints(tmp_path: Path, monkeypatch) -> None:
    original_next_window = SelfPlaySimulator.next_window

    def delayed_next_window(self, windows_done: int, *, eval_protocol_hash: str, league_opponents=None):
        time.sleep(0.05)
        return original_next_window(
            self,
            windows_done,
            eval_protocol_hash=eval_protocol_hash,
            league_opponents=league_opponents,
        )

    monkeypatch.setattr(SelfPlaySimulator, "next_window", delayed_next_window)

    async def _scenario() -> None:
        service = TrainingJobService(
            event_bus=EventBus(),
            checkpoint_root=tmp_path / "training_checkpoints",
        )
        job = service.create_job(
            ruleset_id="classic_v1",
            profile_id=None,
            seed=11,
            params=_fast_params(),
        )

        await service.apply_command(job.id, "start")
        await asyncio.sleep(0.02)
        assert service.list_checkpoints(job.id) == []

        for _ in range(300):
            if service.get_job(job.id).progress.windows_done >= 1:
                break
            await asyncio.sleep(0.01)
        assert service.get_job(job.id).progress.windows_done >= 1
        assert service.list_checkpoints(job.id) == []

        await service.apply_command(job.id, "stop")
        for _ in range(150):
            if service.get_job(job.id).lifecycle_state == "Stopped":
                break
            await asyncio.sleep(0.01)
        assert service.get_job(job.id).lifecycle_state == "Stopped"

    asyncio.run(_scenario())


def test_training_cold_restore_from_store_keeps_progress_without_checkpoints(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "app.sqlite3")
    service = TrainingJobService(
        event_bus=EventBus(),
        checkpoint_root=tmp_path / "training_checkpoints",
        store=store,
    )
    job = service.create_job(
        ruleset_id="classic_v1",
        profile_id=None,
        seed=19,
        params=_fast_params(),
    )
    runtime = service._runtimes[job.id]
    with service._lock:
        for _ in range(4):
            service._run_microbatch_locked(job, runtime)
    before = service.get_job(job.id)

    restored = TrainingJobService(
        event_bus=EventBus(),
        checkpoint_root=tmp_path / "training_checkpoints",
        store=store,
    )
    after = restored.get_job(job.id)

    assert after.progress.games_played == before.progress.games_played
    assert after.progress.windows_done == before.progress.windows_done
    assert after.progress.best_score == before.progress.best_score
    assert after.progress.eval_protocol_hash == before.progress.eval_protocol_hash
    assert restored.list_checkpoints(job.id) == []
