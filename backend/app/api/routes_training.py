from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_training_jobs
from app.schemas import TrainingCommandRequest, TrainingJobCreateRequest, TrainingJobResponse
from app.services.training_jobs import TrainingJobService

router = APIRouter(prefix="/api/v1/training/jobs", tags=["training"])


def _to_response(job) -> TrainingJobResponse:
    return TrainingJobResponse(
        id=job.id,
        ruleset_id=job.ruleset_id,
        lifecycle_state=job.lifecycle_state,
        stage_state=job.stage_state,
        profile_id=job.profile_id,
        seed=job.seed,
        stop_reason=job.stop_reason,
    )


@router.post("", response_model=TrainingJobResponse)
async def create_training_job(
    payload: TrainingJobCreateRequest,
    training_jobs: TrainingJobService = Depends(get_training_jobs),
) -> TrainingJobResponse:
    try:
        job = training_jobs.create_job(payload.ruleset_id, payload.profile_id, payload.seed)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
