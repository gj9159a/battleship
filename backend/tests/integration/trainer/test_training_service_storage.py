import asyncio
import json
import time
from pathlib import Path

from app.bots.selfplay import SelfPlaySimulator
from app.services import EventBus
from app.services.training_jobs import TrainingJobService
from app.trainer import TrainingParams


def test_training_service_checkpoint_roundtrip(tmp_path: Path) -> None:
    async def _scenario() -> None:
        service = TrainingJobService(
            event_bus=EventBus(),
            checkpoint_root=tmp_path / 'training_checkpoints',
        )

        job = service.create_job(
            ruleset_id='classic_v1',
            profile_id=None,
            seed=5,
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

        await service.apply_command(job.id, 'start')

        for _ in range(300):
            checkpoints = service.list_checkpoints(job.id)
            if checkpoints:
                break
            await asyncio.sleep(0.01)
        assert checkpoints

        await service.apply_command(job.id, 'pause')
        for _ in range(300):
            if service.get_job(job.id).lifecycle_state == 'Paused':
                break
            await asyncio.sleep(0.01)
        assert service.get_job(job.id).lifecycle_state == 'Paused'

        checkpoint = checkpoints[0]
        loaded = await service.load_checkpoint(job.id, checkpoint.checkpoint_id)
        assert loaded.progress.batches_done == checkpoint.batches_done
        assert loaded.progress.games_played == checkpoint.games_played

        stopped = await service.apply_command(job.id, 'stop')
        assert stopped.lifecycle_state == 'Stopped'

    asyncio.run(_scenario())


def test_checkpoint_created_only_after_window_eval_finishes(tmp_path: Path, monkeypatch) -> None:
    original_next_window = SelfPlaySimulator.next_window

    def delayed_next_window(self, windows_done: int, *, eval_protocol_hash: str, league_opponents=None):
        time.sleep(0.25)
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
                tick_delay_ms=0,
            ),
        )

        await service.apply_command(job.id, "start")
        await asyncio.sleep(0.05)
        assert service.list_checkpoints(job.id) == []

        checkpoints = []
        for _ in range(400):
            checkpoints = service.list_checkpoints(job.id)
            if checkpoints:
                break
            await asyncio.sleep(0.01)
        assert checkpoints

        await service.apply_command(job.id, "stop")
        for _ in range(300):
            if service.get_job(job.id).lifecycle_state == "Stopped":
                break
            await asyncio.sleep(0.01)
        assert service.get_job(job.id).lifecycle_state == "Stopped"

    asyncio.run(_scenario())


def test_training_cold_restore_keeps_cma_trajectory(tmp_path: Path) -> None:
    params = TrainingParams(
        microbatch_size=5,
        eval_window_batches=1,
        checkpoint_interval_batches=1,
        population_size=6,
        train_split=0.7,
        worker_count=1,
        quality_gate_games=20,
        target_score=1.0,
        early_stop_plateau_windows=100000,
        tick_delay_ms=0,
    )

    service_cont = TrainingJobService(
        event_bus=EventBus(),
        checkpoint_root=tmp_path / "continuous",
    )
    job_cont = service_cont.create_job(ruleset_id="classic_v1", profile_id=None, seed=19, params=params)
    runtime_cont = service_cont._runtimes[job_cont.id]
    with service_cont._lock:
        for _ in range(6):
            service_cont._run_microbatch_locked(job_cont, runtime_cont)
    cont = service_cont.get_job(job_cont.id)

    service_split = TrainingJobService(
        event_bus=EventBus(),
        checkpoint_root=tmp_path / "split",
    )
    job_split = service_split.create_job(ruleset_id="classic_v1", profile_id=None, seed=19, params=params)
    runtime_split = service_split._runtimes[job_split.id]
    with service_split._lock:
        for _ in range(3):
            service_split._run_microbatch_locked(job_split, runtime_split)
    checkpoint = service_split.list_checkpoints(job_split.id)[-1]
    payload = service_split.get_checkpoint_payload(job_split.id, checkpoint.checkpoint_id)
    assert "search_state" in payload
    assert payload["search_state"]["search_policy"] == "sep_cma_es_lite_v1"

    asyncio.run(service_split.load_checkpoint(job_split.id, checkpoint.checkpoint_id))
    runtime_split = service_split._runtimes[job_split.id]
    with service_split._lock:
        for _ in range(3):
            service_split._run_microbatch_locked(job_split, runtime_split)
    split = service_split.get_job(job_split.id)

    assert split.progress.search_state_bootstrapped is False
    assert split.current_weights == cont.current_weights
    assert split.best_weights == cont.best_weights
    assert split.progress.cma_sigma == cont.progress.cma_sigma
    assert split.progress.cma_generation == cont.progress.cma_generation
    assert split.progress.cma_diag_mean == cont.progress.cma_diag_mean
    assert split.progress.cma_diag_min == cont.progress.cma_diag_min
    assert split.progress.cma_diag_max == cont.progress.cma_diag_max
    assert split.progress.cma_mean_incumbent_l2 == cont.progress.cma_mean_incumbent_l2
    assert split.progress.cma_parent_mu == cont.progress.cma_parent_mu
    assert split.progress.cma_mueff == cont.progress.cma_mueff
    assert split.progress.restart_count == cont.progress.restart_count
    assert split.progress.last_score == cont.progress.last_score
    assert split.progress.selection_decision_reason == cont.progress.selection_decision_reason


def test_load_checkpoint_bootstraps_search_state_when_snapshot_missing(tmp_path: Path) -> None:
    service = TrainingJobService(
        event_bus=EventBus(),
        checkpoint_root=tmp_path / "bootstrap-missing",
    )
    job = service.create_job(
        ruleset_id="classic_v1",
        profile_id=None,
        seed=23,
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
            tick_delay_ms=0,
        ),
    )
    runtime = service._runtimes[job.id]
    with service._lock:
        service._run_microbatch_locked(job, runtime)
    checkpoint = service.list_checkpoints(job.id)[-1]

    path = Path(checkpoint.path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("search_state", None)
    path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")

    loaded = asyncio.run(service.load_checkpoint(job.id, checkpoint.checkpoint_id))
    assert loaded.progress.search_state_bootstrapped is True
    assert loaded.progress.search_policy == "sep_cma_es_lite_v1"
