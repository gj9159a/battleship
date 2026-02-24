from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_game_sessions
from app.engine.types import Placement
from app.schemas import GameSessionCreateRequest, GameSessionResponse, ShotRequest, ShotResponse
from app.services.game_sessions import GameSession, GameSessionService

router = APIRouter(prefix="/api/v1/game/sessions", tags=["game"])


def _to_placement(dto) -> Placement:
    return Placement(row=dto.row, col=dto.col, length=dto.length, orientation=dto.orientation)


def _to_response(session: GameSession) -> GameSessionResponse:
    lifecycle_state = "completed" if session.game.is_over else "running"
    return GameSessionResponse(
        id=session.id,
        ruleset_id=session.ruleset_id,
        lifecycle_state=lifecycle_state,
        current_player=session.game.current_player,
        winner=session.game.winner,
        shots=[
            ShotResponse(
                shooter=shot.shooter,
                target=shot.target,
                row=shot.row,
                col=shot.col,
                outcome=shot.outcome,
                game_over=shot.game_over,
                winner=shot.winner,
                next_player=shot.next_player,
            )
            for shot in session.shots
        ],
    )


@router.post("", response_model=GameSessionResponse)
async def create_game_session(
    payload: GameSessionCreateRequest,
    game_sessions: GameSessionService = Depends(get_game_sessions),
) -> GameSessionResponse:
    try:
        session = game_sessions.create_session(
            ruleset_id=payload.ruleset_id,
            player_placements=[_to_placement(item) for item in payload.player_placements],
            opponent_placements=[_to_placement(item) for item in payload.opponent_placements],
            first_player=payload.first_player,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_response(session)


@router.get("/{session_id}", response_model=GameSessionResponse)
async def get_game_session(
    session_id: str,
    game_sessions: GameSessionService = Depends(get_game_sessions),
) -> GameSessionResponse:
    try:
        session = game_sessions.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_response(session)


@router.post("/{session_id}/shots", response_model=ShotResponse)
async def shoot(
    session_id: str,
    payload: ShotRequest,
    game_sessions: GameSessionService = Depends(get_game_sessions),
) -> ShotResponse:
    try:
        result = game_sessions.shoot(session_id=session_id, row=payload.row, col=payload.col)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return ShotResponse(
        shooter=result.shooter,
        target=result.target,
        row=result.row,
        col=result.col,
        outcome=result.outcome,
        game_over=result.game_over,
        winner=result.winner,
        next_player=result.next_player,
    )
