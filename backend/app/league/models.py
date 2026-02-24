from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

PoolType = Literal["baseline", "active", "league"]
SeasonState = Literal[
    "Idle",
    "Running",
    "Pausing",
    "Paused",
    "Stopping",
    "Stopped",
    "Completed",
    "Error",
]


@dataclass(slots=True)
class LeagueRating:
    ruleset_id: str
    bot_version_id: str
    pool_type: PoolType
    mu: float
    sigma: float
    matches_played: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    updated_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())

    @property
    def conservative_score(self) -> float:
        return self.mu - 3 * self.sigma


@dataclass(slots=True)
class LeagueSeason:
    id: str
    ruleset_id: str
    lifecycle_state: SeasonState
    seed: int
    max_matches: int
    microbatch_size: int
    matches_done: int = 0
    stop_reason: str | None = None


@dataclass(frozen=True, slots=True)
class MatchRecord:
    id: str
    ruleset_id: str
    season_id: str | None
    bot_a_id: str
    bot_b_id: str
    winner_id: str | None
    played_at: str
