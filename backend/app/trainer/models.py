from dataclasses import dataclass, field
from typing import Literal

LifecycleState = Literal[
    "Idle",
    "Running",
    "Pausing",
    "Paused",
    "Stopping",
    "Stopped",
    "Completed",
    "Error",
]

StageState = Literal[
    "Warmup",
    "MainOptimization",
    "CandidateEvaluation",
    "PlateauCheck",
    "Finished",
]


@dataclass(slots=True)
class TrainingParams:
    games_per_candidate: int = 128
    epoch_iters: int = 5
    microbatch_size: int = 128
    eval_window_batches: int = 5
    checkpoint_interval_batches: int = 50
    population_size: int = 32
    train_split: float = 0.7
    worker_count: int = 12
    quality_gate_games: int = 256
    quality_gate_min_winrate: float = 0.57
    quality_gate_min_lower_bound: float = 0.53
    target_score: float = 0.8
    improvement_delta: float = 0.01
    plateau_delta: float = 0.01
    plateau_patience_windows: int = 1
    early_stop_plateau_windows: int = 30
    min_windows_before_early_stop: int = 120
    tick_delay_ms: int = 0
    autoevolve_enabled: bool = True
    meta_plateau_patience_cycles: int = 3
    strictness_max_level: int = 3

    def __post_init__(self) -> None:
        if self.games_per_candidate <= 0:
            raise ValueError("games_per_candidate must be > 0")
        if self.epoch_iters <= 0:
            raise ValueError("epoch_iters must be > 0")
        if self.microbatch_size <= 0:
            raise ValueError("microbatch_size must be > 0")
        if self.eval_window_batches <= 0:
            raise ValueError("eval_window_batches must be > 0")
        if self.checkpoint_interval_batches <= 0:
            raise ValueError("checkpoint_interval_batches must be > 0")
        if self.population_size <= 0:
            raise ValueError("population_size must be > 0")
        if self.worker_count <= 0:
            raise ValueError("worker_count must be > 0")
        if self.quality_gate_games <= 0:
            raise ValueError("quality_gate_games must be > 0")
        if self.min_windows_before_early_stop <= 0:
            raise ValueError("min_windows_before_early_stop must be > 0")
        if not 0.5 <= self.train_split <= 0.9:
            raise ValueError("train_split must be in [0.5, 0.9]")
        if not 0.0 <= self.quality_gate_min_winrate <= 1.0:
            raise ValueError("quality_gate_min_winrate must be in [0, 1]")
        if not 0.0 <= self.quality_gate_min_lower_bound <= 1.0:
            raise ValueError("quality_gate_min_lower_bound must be in [0, 1]")
        if self.tick_delay_ms < 0:
            raise ValueError("tick_delay_ms must be >= 0")
        if self.meta_plateau_patience_cycles <= 0:
            raise ValueError("meta_plateau_patience_cycles must be > 0")
        if self.strictness_max_level < 0:
            raise ValueError("strictness_max_level must be >= 0")
        default_games = 128
        default_epoch_iters = 5
        default_microbatch = 128
        default_eval_window = 5

        if self.microbatch_size == default_microbatch and self.games_per_candidate != default_games:
            self.microbatch_size = int(self.games_per_candidate)
        elif self.microbatch_size != default_microbatch and self.games_per_candidate == default_games:
            self.games_per_candidate = int(self.microbatch_size)
        else:
            self.games_per_candidate = int(self.microbatch_size)

        if self.eval_window_batches == default_eval_window and self.epoch_iters != default_epoch_iters:
            self.eval_window_batches = int(self.epoch_iters)
        elif self.eval_window_batches != default_eval_window and self.epoch_iters == default_epoch_iters:
            self.epoch_iters = int(self.eval_window_batches)
        else:
            self.epoch_iters = int(self.eval_window_batches)


@dataclass(slots=True)
class TrainingProgress:
    games_played: int = 0
    batches_done: int = 0
    windows_done: int = 0
    best_score: float = 0.0
    last_score: float = 0.0
    plateau_windows: int = 0
    candidate_streak: int = 0
    stage_enter_window: int = 0
    cycle_index: int = 0
    current_population_size: int = 0
    strictness_level: int = 0
    meta_plateau_counter: int = 0
    champion_gate_lcb: float = 0.0
    eval_protocol_hash: str = ""
    last_wr_baseline: float = 0.0
    last_wr_active: float = 0.0
    last_avg_turns_win: float = 0.0
    last_avg_shots_to_sink_all: float = 0.0
    last_p95_shots_to_sink_all: float = 0.0
    last_avg_shots_to_first_hit: float = 0.0
    last_avg_shots_after_first_hit_to_sink_all: float = 0.0
    last_avg_misses_before_first_hit: float = 0.0
    last_eval_seed_anchor: int = 0
    last_incumbent_seed_anchor: int = 0
    last_eval_paired: bool = False
    last_eval_mirrored: bool = True
    selection_robust_score_candidate: float = 0.0
    selection_robust_score_incumbent: float = 0.0
    selection_robust_delta: float = 0.0
    selection_noninferiority_passed: bool = False
    selection_attack_efficiency_candidate: float = 0.0
    selection_attack_efficiency_incumbent: float = 0.0
    selection_attack_delta: float = 0.0
    selection_tiebreak_used: bool = False
    selection_decision_reason: str = "unknown"
    elite_candidates_evaluated: int = 0
    elite_selected_candidate_index: int = -1
    elite_selection_reason: str = "unknown"
    sigma_mean: float = 0.0
    sigma_min: float = 0.0
    sigma_max: float = 0.0
    search_policy: str = "sep_cma_es_lite_v1"
    cma_sigma: float = 0.0
    cma_diag_mean: float = 0.0
    cma_diag_min: float = 0.0
    cma_diag_max: float = 0.0
    cma_generation: int = 0
    cma_mean_incumbent_l2: float = 0.0
    cma_parent_mu: int = 0
    cma_mueff: float = 0.0
    search_state_bootstrapped: bool = False
    restart_count: int = 0
    last_restart_reason: str = "none"
    last_restart_anchor_score: float = 0.0
    last_restart_window: int = -1
    elite_fallback_used: bool = False
    frozen_suite_summaries: dict[str, dict[str, object]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TrainingCheckpoint:
    checkpoint_id: str
    job_id: str
    path: str
    batches_done: int
    games_played: int
    best_score: float
    stage_state: str | None


TrainingWeights = dict[str, float]

SuiteKind = Literal["random", "strong"]
SuiteSubjectType = Literal["bot_version", "checkpoint"]
SuiteTier = Literal["canonical", "ci_smoke"]


@dataclass(frozen=True, slots=True)
class FrozenSuite:
    suite_id: str
    name: str
    ruleset_id: str
    suite_kind: SuiteKind
    suite_tier: SuiteTier
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


@dataclass(frozen=True, slots=True)
class FrozenSuiteRun:
    run_id: str
    suite_id: str
    created_at: str
    subject_type: SuiteSubjectType
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
