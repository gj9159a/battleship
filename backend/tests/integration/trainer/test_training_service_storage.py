import asyncio
from pathlib import Path

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
                budget_games=100000,
                microbatch_size=5,
                eval_window_batches=1,
                checkpoint_interval_batches=1,
                target_score=1.0,
                early_stop_plateau_windows=100000,
                tick_delay_ms=1,
            ),
        )

        await service.apply_command(job.id, 'start')

        for _ in range(100):
            checkpoints = service.list_checkpoints(job.id)
            if checkpoints:
                break
            await asyncio.sleep(0.01)
        assert checkpoints

        await service.apply_command(job.id, 'pause')
        for _ in range(100):
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
