from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_league_service
from app.schemas import (
    LeagueJobCommandRequest,
    LeagueMatchRecordRequest,
    LeagueMatchResponse,
    LeagueMatrixCellResponse,
    LeagueRatingResponse,
    LeagueRegisterBotRequest,
    LeagueSeasonCreateRequest,
    LeagueSeasonResponse,
)
from app.services.league import LeagueService

router = APIRouter(prefix="/api/v1/league", tags=["league"])


def _to_rating_response(row) -> LeagueRatingResponse:
    wins = row.wins
    total = row.matches_played
    winrate = wins / total if total else 0.0
    return LeagueRatingResponse(
        ruleset_id=row.ruleset_id,
        bot_version_id=row.bot_version_id,
        pool_type=row.pool_type,
        mu=row.mu,
        sigma=row.sigma,
        conservative_score=row.conservative_score,
        matches_played=row.matches_played,
        wins=row.wins,
        losses=row.losses,
        draws=row.draws,
        winrate=round(winrate, 6),
        updated_at=row.updated_at,
    )


def _to_season_response(season) -> LeagueSeasonResponse:
    return LeagueSeasonResponse(
        id=season.id,
        ruleset_id=season.ruleset_id,
        lifecycle_state=season.lifecycle_state,
        seed=season.seed,
        max_matches=season.max_matches,
        microbatch_size=season.microbatch_size,
        matches_done=season.matches_done,
        stop_reason=season.stop_reason,
    )


@router.post("/{ruleset_id}/bots", response_model=LeagueRatingResponse)
async def register_league_bot(
    ruleset_id: str,
    payload: LeagueRegisterBotRequest,
    league_service: LeagueService = Depends(get_league_service),
) -> LeagueRatingResponse:
    try:
        row = league_service.register_bot(
            ruleset_id=ruleset_id,
            bot_version_id=payload.bot_version_id,
            pool_type=payload.pool_type,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_rating_response(row)


@router.get("/{ruleset_id}/table", response_model=list[LeagueRatingResponse])
async def get_league_table(
    ruleset_id: str,
    league_service: LeagueService = Depends(get_league_service),
) -> list[LeagueRatingResponse]:
    try:
        rows = league_service.list_table(ruleset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [_to_rating_response(row) for row in rows]


@router.get("/{ruleset_id}/matchup-matrix", response_model=list[LeagueMatrixCellResponse])
async def get_matchup_matrix(
    ruleset_id: str,
    league_service: LeagueService = Depends(get_league_service),
) -> list[LeagueMatrixCellResponse]:
    try:
        matrix = league_service.get_matchup_matrix(ruleset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [LeagueMatrixCellResponse(**row) for row in matrix]


@router.post("/{ruleset_id}/matches", response_model=LeagueMatchResponse)
async def record_league_match(
    ruleset_id: str,
    payload: LeagueMatchRecordRequest,
    league_service: LeagueService = Depends(get_league_service),
) -> LeagueMatchResponse:
    try:
        match = league_service.record_match(
            ruleset_id=ruleset_id,
            bot_a_id=payload.bot_a_id,
            bot_b_id=payload.bot_b_id,
            winner_id=payload.winner_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return LeagueMatchResponse(
        id=match.id,
        ruleset_id=match.ruleset_id,
        season_id=match.season_id,
        bot_a_id=match.bot_a_id,
        bot_b_id=match.bot_b_id,
        winner_id=match.winner_id,
        played_at=match.played_at,
    )


@router.post("/seasons", response_model=LeagueSeasonResponse)
async def create_league_season(
    payload: LeagueSeasonCreateRequest,
    league_service: LeagueService = Depends(get_league_service),
) -> LeagueSeasonResponse:
    try:
        season = league_service.create_season(
            ruleset_id=payload.ruleset_id,
            seed=payload.seed,
            max_matches=payload.max_matches,
            microbatch_size=payload.microbatch_size,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_season_response(season)


@router.get("/seasons/{season_id}", response_model=LeagueSeasonResponse)
async def get_league_season(
    season_id: str,
    league_service: LeagueService = Depends(get_league_service),
) -> LeagueSeasonResponse:
    try:
        season = league_service.get_season(season_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_season_response(season)


@router.post("/jobs/{season_id}/commands", response_model=LeagueSeasonResponse)
async def command_league_job(
    season_id: str,
    payload: LeagueJobCommandRequest,
    league_service: LeagueService = Depends(get_league_service),
) -> LeagueSeasonResponse:
    try:
        season = await league_service.command_season(season_id=season_id, command=payload.command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_season_response(season)
