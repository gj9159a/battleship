from typing import Literal

from pydantic import BaseModel, Field


class RulesetResponse(BaseModel):
    id: str
    name: str
    board_size: int
    fleet: list[int]
    placement_no_touch: bool
    extra_turn_on_hit: bool
    is_active: bool
    is_archived: bool


class RulesetCreateRequest(BaseModel):
    id: str
    name: str
    board_size: int = Field(gt=0)
    fleet: list[int] = Field(min_length=1)
    placement_no_touch: bool = False
    extra_turn_on_hit: bool = True


class RulesetCloneRequest(BaseModel):
    new_id: str
    new_name: str


class RulesetUpdateRequest(BaseModel):
    name: str | None = None
    board_size: int | None = Field(default=None, gt=0)
    fleet: list[int] | None = Field(default=None, min_length=1)
    placement_no_touch: bool | None = None
    extra_turn_on_hit: bool | None = None


class BotVersionResponse(BaseModel):
    bot_version_id: str
    ruleset_id: str
    policy_type: str
    feature_schema_version: str
    lookahead_policy_version: str
    weights: dict[str, float]
    source_job_id: str | None
    source_checkpoint_id: str | None
    tags: list[str]
    created_at: str


class BotVersionCreateFromCheckpointRequest(BaseModel):
    job_id: str
    checkpoint_id: str
    bot_version_id: str | None = None
    policy_type: str = "probability_strong"
    feature_schema_version: str = "classic_features_v1"
    lookahead_policy_version: str = "adaptive_v1"


class BotVersionLabelsUpdateRequest(BaseModel):
    is_baseline: bool | None = None
    is_league: bool | None = None
    is_legacy: bool | None = None


class TrainingCheckpointIndexResponse(BaseModel):
    job_id: str
    checkpoint_id: str
    ruleset_id: str
    batches_done: int
    games_played: int
    best_score: float
    stage_state: str | None


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
    microbatch_size: int = Field(default=100, gt=0)
    eval_window_batches: int = Field(default=2, gt=0)
    checkpoint_interval_batches: int = Field(default=50, gt=0)
    population_size: int = Field(default=32, gt=0)
    train_split: float = Field(default=0.7, ge=0.5, le=0.9)
    worker_count: int = Field(default=12, gt=0)
    quality_gate_games: int = Field(default=256, gt=0)
    quality_gate_min_winrate: float = Field(default=0.57, ge=0.0, le=1.0)
    quality_gate_min_lower_bound: float = Field(default=0.53, ge=0.0, le=1.0)
    target_score: float = Field(default=0.8, ge=0.0, le=1.0)
    improvement_delta: float = Field(default=0.008, ge=0.0, le=1.0)
    plateau_delta: float = Field(default=0.0015, ge=0.0, le=1.0)
    plateau_patience_windows: int = Field(default=8, gt=0)
    early_stop_plateau_windows: int = Field(default=30, gt=0)
    min_windows_before_early_stop: int = Field(default=120, gt=0)
    tick_delay_ms: int = Field(default=0, ge=0)
    autoevolve_enabled: bool = True
    meta_plateau_patience_cycles: int = Field(default=3, gt=0)
    strictness_max_level: int = Field(default=3, ge=0)


class TrainingJobCreateRequest(BaseModel):
    ruleset_id: str
    profile_id: str | None = None
    seed_bot_version_id: str | None = None
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
    cycle_index: int
    strictness_level: int
    meta_plateau_counter: int
    champion_gate_lcb: float
    eval_protocol_hash: str


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
    seed_bot_version_id: str | None
    seed: int | None
    stop_reason: str | None
    current_weights: dict[str, float]
    best_weights: dict[str, float]
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
