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
    extra_turn_on_hit: bool = False


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
    games_per_candidate: int = Field(default=128, gt=0)
    epoch_iters: int = Field(default=5, gt=0)
    microbatch_size: int = Field(default=128, gt=0)
    eval_window_batches: int = Field(default=5, gt=0)
    checkpoint_interval_batches: int = Field(default=50, gt=0)
    population_size: int = Field(default=32, gt=0)
    train_split: float = Field(default=0.7, ge=0.5, le=0.9)
    worker_count: int = Field(default=12, gt=0)
    quality_gate_games: int = Field(default=256, gt=0)
    quality_gate_min_winrate: float = Field(default=0.57, ge=0.0, le=1.0)
    quality_gate_min_lower_bound: float = Field(default=0.53, ge=0.0, le=1.0)
    target_score: float = Field(default=0.8, ge=0.0, le=1.0)
    improvement_delta: float = Field(default=0.01, ge=0.0, le=1.0)
    plateau_delta: float = Field(default=0.01, ge=0.0, le=1.0)
    plateau_patience_windows: int = Field(default=1, gt=0)
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
    current_population_size: int
    strictness_level: int
    meta_plateau_counter: int
    champion_gate_lcb: float
    eval_protocol_hash: str
    last_wr_baseline: float
    last_wr_active: float
    last_avg_turns_win: float
    last_avg_shots_to_sink_all: float
    last_p95_shots_to_sink_all: float
    last_avg_shots_to_first_hit: float
    last_avg_shots_after_first_hit_to_sink_all: float
    last_avg_misses_before_first_hit: float
    last_eval_seed_anchor: int
    last_incumbent_seed_anchor: int
    last_eval_paired: bool
    last_eval_mirrored: bool
    selection_robust_score_candidate: float
    selection_robust_score_incumbent: float
    selection_robust_delta: float
    selection_noninferiority_passed: bool
    selection_attack_efficiency_candidate: float
    selection_attack_efficiency_incumbent: float
    selection_attack_delta: float
    selection_tiebreak_used: bool
    selection_decision_reason: str
    elite_candidates_evaluated: int
    elite_selected_candidate_index: int
    elite_selection_reason: str
    sigma_mean: float
    sigma_min: float
    sigma_max: float
    search_policy: str
    cma_sigma: float
    cma_diag_mean: float
    cma_diag_min: float
    cma_diag_max: float
    cma_generation: int
    cma_mean_incumbent_l2: float
    cma_parent_mu: int
    cma_mueff: float
    search_state_bootstrapped: bool
    restart_count: int
    last_restart_reason: str
    last_restart_anchor_score: float
    last_restart_window: int
    elite_fallback_used: bool
    frozen_suite_summaries: dict[str, dict[str, object]]


class TrainingCheckpointResponse(BaseModel):
    checkpoint_id: str
    job_id: str
    path: str
    batches_done: int
    games_played: int
    best_score: float
    stage_state: str | None


class TrainingWindowMetricResponse(BaseModel):
    batch: int
    window: int
    score: float
    best: float
    plateau: int
    cycle: int
    population_size: int
    window_evaluated: bool
    avg_shots_to_sink_all: float
    p95_shots_to_sink_all: float
    avg_shots_to_first_hit: float
    avg_shots_after_first_hit_to_sink_all: float
    selection_decision_reason: str
    selection_tiebreak_used: bool
    selection_noninferiority_passed: bool
    selection_robust_delta: float
    selection_attack_delta: float
    sigma_mean: float
    sigma_min: float
    sigma_max: float
    restart_count: int
    last_restart_reason: str
    last_restart_window: int
    elite_fallback_used: bool


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


class FrozenSuiteResponse(BaseModel):
    suite_id: str
    name: str
    ruleset_id: str
    suite_kind: Literal["random", "strong"]
    suite_tier: Literal["canonical", "ci_smoke"]
    created_at: str
    suite_protocol_hash: str
    seed_anchor: int
    seed_count: int
    seed_derivation_scheme: str
    games_per_seed: int
    series_count: int
    mirrored_first_player: bool
    opponent_policy_type: str
    opponent_bot_version_id: str | None
    opponent_weights: dict[str, float]
    opponent_lookahead_policy_version: str


class FrozenSuiteRunResponse(BaseModel):
    run_id: str
    suite_id: str
    created_at: str
    subject_type: Literal["bot_version", "checkpoint"]
    subject_ref: str
    suite_protocol_hash: str
    eval_seed_anchor: int
    seed_count: int
    games_per_seed: int
    paired_eval: bool
    mirrored_first_player: bool
    winrate: float
    lcb: float
    avg_shots_to_sink_all: float
    p95_shots_to_sink_all: float
    avg_shots_to_first_hit: float
    avg_shots_after_first_hit_to_sink_all: float
    avg_misses_before_first_hit: float
    raw_metrics: dict[str, str | float | int | bool | None]


class FrozenSuiteRunBotVersionRequest(BaseModel):
    bot_version_id: str


class FrozenSuiteRunCheckpointRequest(BaseModel):
    job_id: str
    checkpoint_id: str


class FrozenSuiteEnsureRequest(BaseModel):
    ruleset_id: str
    suite_tier: Literal["canonical", "ci_smoke"] = "canonical"


class PlacementBiasAnalyzeRequest(BaseModel):
    ruleset_id: str
    sample_count: int = Field(default=5000, gt=0, le=100000)
    seed_anchor: int | None = None


class PlacementBiasReportResponse(BaseModel):
    report_id: str
    ruleset_id: str
    sample_count: int
    seed_anchor: int
    seed_derivation_scheme: str
    generator_version: str
    created_at: str
    occupancy_heatmap: list[list[float]]
    occupancy_by_ship_len: dict[str, list[list[float]]]
    orientation_stats_by_len: dict[str, dict[str, float | int]]
    edge_center_bias: dict[str, float]
    corner_bias: dict[str, float]
    retry_stats: dict[str, object]
    seed_reproducibility_check: dict[str, object]
