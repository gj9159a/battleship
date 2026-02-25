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
    _ = ruleset_id
    _ = training_jobs
    return []


@router.post("/from-checkpoint", response_model=BotVersionResponse)
async def create_bot_from_checkpoint(
    payload: BotVersionCreateFromCheckpointRequest,
    training_jobs: TrainingJobService = Depends(get_training_jobs),
    bot_catalog: BotCatalogService = Depends(get_bot_catalog),
) -> BotVersionResponse:
    _ = payload
    _ = training_jobs
    _ = bot_catalog
    raise HTTPException(status_code=410, detail="Checkpoint system is disabled")


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
