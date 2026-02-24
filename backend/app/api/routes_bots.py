from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_bot_catalog, get_training_jobs
from app.schemas import (
    BotVersionCreateFromCheckpointRequest,
    BotVersionLabelsUpdateRequest,
    BotVersionResponse,
    TrainingCheckpointIndexResponse,
)
from app.services import BotCatalogService
from app.services.training_jobs import TrainingJobService

router = APIRouter(prefix="/api/v1/bots", tags=["bots"])


def _to_response(bot) -> BotVersionResponse:
    return BotVersionResponse(
        bot_version_id=bot.bot_version_id,
        ruleset_id=bot.ruleset_id,
        policy_type=bot.policy_type,
        feature_schema_version=bot.feature_schema_version,
        lookahead_policy_version=bot.lookahead_policy_version,
        weights=dict(bot.weights),
        source_job_id=bot.source_job_id,
        source_checkpoint_id=bot.source_checkpoint_id,
        tags=sorted(bot.tags),
        created_at=bot.created_at,
    )


@router.get("", response_model=list[BotVersionResponse])
async def get_bots(
    ruleset_id: str | None = None,
    policy_type: str | None = None,
    feature_schema_version: str | None = None,
    include_legacy: bool = True,
    bot_catalog: BotCatalogService = Depends(get_bot_catalog),
) -> list[BotVersionResponse]:
    bots = bot_catalog.list_bots(
        ruleset_id=ruleset_id,
        policy_type=policy_type,
        feature_schema_version=feature_schema_version,
        include_legacy=include_legacy,
    )
    return [_to_response(bot) for bot in bots]


@router.get("/checkpoints", response_model=list[TrainingCheckpointIndexResponse])
async def get_bots_checkpoints(
    ruleset_id: str | None = None,
    training_jobs: TrainingJobService = Depends(get_training_jobs),
) -> list[TrainingCheckpointIndexResponse]:
    rows = training_jobs.list_all_checkpoints(ruleset_id=ruleset_id)
    response = [
        TrainingCheckpointIndexResponse(
            job_id=job.id,
            checkpoint_id=checkpoint.checkpoint_id,
            ruleset_id=job.ruleset_id,
            batches_done=checkpoint.batches_done,
            games_played=checkpoint.games_played,
            best_score=checkpoint.best_score,
            stage_state=checkpoint.stage_state,
        )
        for job, checkpoint in rows
    ]
    response.sort(key=lambda row: (row.best_score, row.batches_done), reverse=True)
    return response


@router.post("/from-checkpoint", response_model=BotVersionResponse)
async def create_bot_from_checkpoint(
    payload: BotVersionCreateFromCheckpointRequest,
    training_jobs: TrainingJobService = Depends(get_training_jobs),
    bot_catalog: BotCatalogService = Depends(get_bot_catalog),
) -> BotVersionResponse:
    try:
        job = training_jobs.get_job(payload.job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    checkpoints = training_jobs.list_checkpoints(payload.job_id)
    checkpoint = next((item for item in checkpoints if item.checkpoint_id == payload.checkpoint_id), None)
    if checkpoint is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown checkpoint_id={payload.checkpoint_id} for job_id={payload.job_id}",
        )

    bot_version_id = payload.bot_version_id or f"{job.ruleset_id}-{payload.checkpoint_id}"
    try:
        checkpoint_payload = training_jobs.get_checkpoint_payload(payload.job_id, payload.checkpoint_id)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    weights = checkpoint_payload.get("best_weights") or checkpoint_payload.get("current_weights") or {}
    if not weights:
        raise HTTPException(
            status_code=409,
            detail=f"Checkpoint {payload.checkpoint_id} has no weights payload",
        )

    try:
        created = bot_catalog.create_from_checkpoint(
            bot_version_id=bot_version_id,
            ruleset_id=job.ruleset_id,
            checkpoint=checkpoint,
            weights=weights,
            policy_type=payload.policy_type,
            feature_schema_version=payload.feature_schema_version,
            lookahead_policy_version=payload.lookahead_policy_version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _to_response(created)


@router.get("/{bot_version_id}", response_model=BotVersionResponse)
async def get_bot(
    bot_version_id: str,
    bot_catalog: BotCatalogService = Depends(get_bot_catalog),
) -> BotVersionResponse:
    try:
        bot = bot_catalog.get_bot(bot_version_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_response(bot)


@router.patch("/{bot_version_id}/labels", response_model=BotVersionResponse)
async def patch_bot_labels(
    bot_version_id: str,
    payload: BotVersionLabelsUpdateRequest,
    bot_catalog: BotCatalogService = Depends(get_bot_catalog),
) -> BotVersionResponse:
    try:
        updated = bot_catalog.update_labels(
            bot_version_id,
            is_baseline=payload.is_baseline,
            is_league=payload.is_league,
            is_legacy=payload.is_legacy,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_response(updated)
