from fastapi import APIRouter, HTTPException

from app.rulesets import (
    activate_ruleset,
    archive_ruleset,
    clone_ruleset,
    create_ruleset,
    get_active_ruleset_id,
    get_ruleset,
    is_ruleset_archived,
    list_rulesets,
    update_ruleset,
)
from app.schemas import RulesetCloneRequest, RulesetCreateRequest, RulesetResponse, RulesetUpdateRequest

router = APIRouter(prefix="/api/v1/rulesets", tags=["rulesets"])


def _to_response(ruleset_id: str) -> RulesetResponse:
    ruleset = get_ruleset(ruleset_id)
    active_ruleset_id = get_active_ruleset_id()
    return RulesetResponse(
        id=ruleset.id,
        name=ruleset.name,
        board_size=ruleset.board_size,
        fleet=list(ruleset.fleet),
        placement_no_touch=ruleset.placement_no_touch,
        extra_turn_on_hit=ruleset.extra_turn_on_hit,
        is_active=ruleset.id == active_ruleset_id,
        is_archived=is_ruleset_archived(ruleset.id),
    )


@router.get("", response_model=list[RulesetResponse])
async def get_rulesets(include_archived: bool = False) -> list[RulesetResponse]:
    return [_to_response(ruleset.id) for ruleset in list_rulesets(include_archived=include_archived)]


@router.get("/active", response_model=RulesetResponse)
async def get_active_ruleset() -> RulesetResponse:
    return _to_response(get_active_ruleset_id())


@router.post("", response_model=RulesetResponse)
async def create_ruleset_route(payload: RulesetCreateRequest) -> RulesetResponse:
    try:
        created = create_ruleset(
            ruleset_id=payload.id,
            name=payload.name,
            board_size=payload.board_size,
            fleet=tuple(payload.fleet),
            placement_no_touch=payload.placement_no_touch,
            extra_turn_on_hit=payload.extra_turn_on_hit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_response(created.id)


@router.patch("/{ruleset_id}", response_model=RulesetResponse)
async def update_ruleset_route(ruleset_id: str, payload: RulesetUpdateRequest) -> RulesetResponse:
    try:
        updated = update_ruleset(
            ruleset_id=ruleset_id,
            name=payload.name,
            board_size=payload.board_size,
            fleet=tuple(payload.fleet) if payload.fleet is not None else None,
            placement_no_touch=payload.placement_no_touch,
            extra_turn_on_hit=payload.extra_turn_on_hit,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_response(updated.id)


@router.post("/{ruleset_id}/clone", response_model=RulesetResponse)
async def clone_ruleset_route(ruleset_id: str, payload: RulesetCloneRequest) -> RulesetResponse:
    try:
        cloned = clone_ruleset(ruleset_id, payload.new_id, payload.new_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_response(cloned.id)


@router.post("/{ruleset_id}/archive", response_model=RulesetResponse)
async def archive_ruleset_route(ruleset_id: str) -> RulesetResponse:
    try:
        archived = archive_ruleset(ruleset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_response(archived.id)


@router.post("/{ruleset_id}/activate", response_model=RulesetResponse)
async def activate_ruleset_route(ruleset_id: str) -> RulesetResponse:
    try:
        active = activate_ruleset(ruleset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_response(active.id)
