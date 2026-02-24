from dataclasses import dataclass
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
    budget_games: int = 2000
    microbatch_size: int = 50
    eval_window_batches: int = 2
    checkpoint_interval_batches: int = 5
    target_score: float = 0.72
    improvement_delta: float = 0.01
    plateau_delta: float = 0.003
    plateau_patience_windows: int = 4
    early_stop_plateau_windows: int = 8
    tick_delay_ms: int = 0

    def __post_init__(self) -> None:
        if self.budget_games <= 0:
            raise ValueError("budget_games must be > 0")
        if self.microbatch_size <= 0:
            raise ValueError("microbatch_size must be > 0")
        if self.eval_window_batches <= 0:
            raise ValueError("eval_window_batches must be > 0")
        if self.checkpoint_interval_batches <= 0:
            raise ValueError("checkpoint_interval_batches must be > 0")
        if self.tick_delay_ms < 0:
            raise ValueError("tick_delay_ms must be >= 0")


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
