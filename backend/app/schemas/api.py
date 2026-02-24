from typing import Literal

from pydantic import BaseModel, Field


class PlacementDTO(BaseModel):
    row: int = Field(ge=0)
    col: int = Field(ge=0)
    length: int = Field(gt=0)
    orientation: Literal["H", "V"]


class GameSessionCreateRequest(BaseModel):
    ruleset_id: str
    player_placements: list[PlacementDTO]
    opponent_placements: list[PlacementDTO]
    first_player: Literal[0, 1] = 0


class ShotRequest(BaseModel):
    row: int = Field(ge=0)
    col: int = Field(ge=0)


class ShotResponse(BaseModel):
    shooter: int
    target: int
    row: int
    col: int
    outcome: Literal["miss", "hit", "sunk"]
    game_over: bool
    winner: int | None
    next_player: int


class GameSessionResponse(BaseModel):
    id: str
    ruleset_id: str
    lifecycle_state: Literal["running", "completed"]
    current_player: int
    winner: int | None
    shots: list[ShotResponse]


class TrainingJobCreateRequest(BaseModel):
    ruleset_id: str
    profile_id: str | None = None
    seed: int | None = None


class TrainingCommandRequest(BaseModel):
    command: Literal["start", "pause", "resume", "stop"]


class TrainingJobResponse(BaseModel):
    id: str
    ruleset_id: str
    lifecycle_state: Literal[
        "Idle",
        "Running",
        "Pausing",
        "Paused",
        "Stopping",
        "Stopped",
        "Completed",
        "Error",
    ]
    stage_state: str | None
    profile_id: str | None
    seed: int | None
    stop_reason: str | None
