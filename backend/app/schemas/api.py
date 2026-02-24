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


class TrainingParamsDTO(BaseModel):
    budget_games: int = Field(default=2000, gt=0)
    microbatch_size: int = Field(default=50, gt=0)
    eval_window_batches: int = Field(default=2, gt=0)
    checkpoint_interval_batches: int = Field(default=5, gt=0)
    target_score: float = Field(default=0.72, ge=0.0, le=1.0)
    improvement_delta: float = Field(default=0.01, ge=0.0, le=1.0)
    plateau_delta: float = Field(default=0.003, ge=0.0, le=1.0)
    plateau_patience_windows: int = Field(default=4, gt=0)
    early_stop_plateau_windows: int = Field(default=8, gt=0)
    tick_delay_ms: int = Field(default=0, ge=0)


class TrainingJobCreateRequest(BaseModel):
    ruleset_id: str
    profile_id: str | None = None
    seed: int | None = None
    params: TrainingParamsDTO | None = None


class TrainingCommandRequest(BaseModel):
    command: Literal["start", "pause", "resume", "stop"]


class TrainingProgressDTO(BaseModel):
    games_played: int
    batches_done: int
    windows_done: int
    best_score: float
    last_score: float
    plateau_windows: int


class TrainingCheckpointResponse(BaseModel):
    checkpoint_id: str
    job_id: str
    path: str
    batches_done: int
    games_played: int
    best_score: float
    stage_state: str | None


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
    params: TrainingParamsDTO
    progress: TrainingProgressDTO


class LeagueRegisterBotRequest(BaseModel):
    bot_version_id: str
    pool_type: Literal["baseline", "active", "league"] = "active"


class LeagueRatingResponse(BaseModel):
    ruleset_id: str
    bot_version_id: str
    pool_type: Literal["baseline", "active", "league"]
    mu: float
    sigma: float
    conservative_score: float
    matches_played: int
    wins: int
    losses: int
    draws: int
    winrate: float
    updated_at: str


class LeagueMatchRecordRequest(BaseModel):
    bot_a_id: str
    bot_b_id: str
    winner_id: str | None


class LeagueMatchResponse(BaseModel):
    id: str
    ruleset_id: str
    season_id: str | None
    bot_a_id: str
    bot_b_id: str
    winner_id: str | None
    played_at: str


class LeagueMatrixCellResponse(BaseModel):
    bot_a_id: str
    bot_b_id: str
    wins_a: int
    wins_b: int
    total: int


class LeagueSeasonCreateRequest(BaseModel):
    ruleset_id: str
    seed: int = 0
    max_matches: int = Field(default=200, gt=0)
    microbatch_size: int = Field(default=20, gt=0)


class LeagueJobCommandRequest(BaseModel):
    command: Literal["start", "pause", "resume", "stop"]


class LeagueSeasonResponse(BaseModel):
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
    seed: int
    max_matches: int
    microbatch_size: int
    matches_done: int
    stop_reason: str | None
