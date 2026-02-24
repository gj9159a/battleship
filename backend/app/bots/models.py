from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(slots=True)
class BotVersion:
    bot_version_id: str
    ruleset_id: str
    policy_type: str
    feature_schema_version: str
    lookahead_policy_version: str
    weights: dict[str, float] = field(default_factory=dict)
    source_job_id: str | None = None
    source_checkpoint_id: str | None = None
    tags: set[str] = field(default_factory=set)
    created_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
