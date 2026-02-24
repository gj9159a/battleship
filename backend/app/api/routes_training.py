from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_bot_catalog, get_training_jobs
from app.schemas import (
    TrainingCheckpointResponse,
    TrainingCommandRequest,
    TrainingJobCreateRequest,
    TrainingJobResponse,
    TrainingParamsDTO,
    TrainingProgressDTO,
)
from app.services.training_jobs import TrainingJobService
from app.services import BotCatalogService
from app.trainer import TrainingParams

router = APIRouter(prefix="/api/v1/training/jobs", tags=["training"])


def _to_response(job) -> TrainingJobResponse:
    return TrainingJobResponse(
        id=job.id,
        ruleset_id=job.ruleset_id,
        lifecycle_state=job.lifecycle_state,
        stage_state=job.stage_state,
        profile_id=job.profile_id,
        seed_bot_version_id=job.seed_bot_version_id,
        seed=job.seed,
        stop_reason=job.stop_reason,
        current_weights=dict(job.current_weights),
        best_weights=dict(job.best_weights),
        params=TrainingParamsDTO(
            budget_games=job.params.budget_games,
            microbatch_size=job.params.microbatch_size,
            eval_window_batches=job.params.eval_window_batches,
            checkpoint_interval_batches=job.params.checkpoint_interval_batches,
            target_score=job.params.target_score,
            improvement_delta=job.params.improvement_delta,
            plateau_delta=job.params.plateau_delta,
            plateau_patience_windows=job.params.plateau_patience_windows,
            early_stop_plateau_windows=job.params.early_stop_plateau_windows,
            tick_delay_ms=job.params.tick_delay_ms,
        ),
        progress=TrainingProgressDTO(
            games_played=job.progress.games_played,
            batches_done=job.progress.batches_done,
            windows_done=job.progress.windows_done,
            best_score=job.progress.best_score,
            last_score=job.progress.last_score,
            plateau_windows=job.progress.plateau_windows,
        ),
    )


@router.post("", response_model=TrainingJobResponse)
async def create_training_job(
    payload: TrainingJobCreateRequest,
    training_jobs: TrainingJobService = Depends(get_training_jobs),
    bot_catalog: BotCatalogService = Depends(get_bot_catalog),
) -> TrainingJobResponse:
    try:
        seed_weights = None
        if payload.seed_bot_version_id:
            seed_bot = bot_catalog.get_bot(payload.seed_bot_version_id)
            if seed_bot.ruleset_id != payload.ruleset_id:
                raise ValueError(
                    f"seed_bot_version_id ruleset mismatch: {seed_bot.ruleset_id} != {payload.ruleset_id}"
                )
            seed_weights = dict(seed_bot.weights)

        params = TrainingParams(**payload.params.model_dump()) if payload.params else TrainingParams()
        job = training_jobs.create_job(
            payload.ruleset_id,
            payload.profile_id,
            payload.seed_bot_version_id,
            payload.seed,
            seed_weights=seed_weights,
            params=params,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_response(job)


@router.get("/{job_id}", response_model=TrainingJobResponse)
async def get_training_job(
    job_id: str,
    training_jobs: TrainingJobService = Depends(get_training_jobs),
) -> TrainingJobResponse:
    try:
        job = training_jobs.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_response(job)


@router.get("/{job_id}/checkpoints", response_model=list[TrainingCheckpointResponse])
async def get_training_checkpoints(
    job_id: str,
    training_jobs: TrainingJobService = Depends(get_training_jobs),
) -> list[TrainingCheckpointResponse]:
    try:
        checkpoints = training_jobs.list_checkpoints(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [
        TrainingCheckpointResponse(
            checkpoint_id=checkpoint.checkpoint_id,
            job_id=checkpoint.job_id,
            path=checkpoint.path,
            batches_done=checkpoint.batches_done,
            games_played=checkpoint.games_played,
            best_score=checkpoint.best_score,
            stage_state=checkpoint.stage_state,
        )
        for checkpoint in checkpoints
    ]


@router.post("/{job_id}/resume-from/{checkpoint_id}", response_model=TrainingJobResponse)
async def load_training_checkpoint(
    job_id: str,
    checkpoint_id: str,
    training_jobs: TrainingJobService = Depends(get_training_jobs),
) -> TrainingJobResponse:
    try:
        job = await training_jobs.load_checkpoint(job_id, checkpoint_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_response(job)


@router.post("/{job_id}/commands", response_model=TrainingJobResponse)
async def command_training_job(
    job_id: str,
    payload: TrainingCommandRequest,
    training_jobs: TrainingJobService = Depends(get_training_jobs),
) -> TrainingJobResponse:
    try:
        job = await training_jobs.apply_command(job_id, payload.command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_response(job)
