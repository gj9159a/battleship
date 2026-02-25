import threading
from dataclasses import replace

from app.bots import BotVersion
from app.bots.policy import normalize_weights
from app.rulesets import get_ruleset
from app.storage import SQLiteStore
from app.trainer import TrainingCheckpoint


class BotCatalogService:
    def __init__(self, store: SQLiteStore | None = None) -> None:
        self._bots: dict[str, BotVersion] = {}
        self._lock = threading.RLock()
        self._store = store
        if self._store is not None:
            for bot in self._store.load_bot_versions():
                self._bots[bot.bot_version_id] = bot

    def list_bots(
        self,
        *,
        ruleset_id: str | None = None,
        policy_type: str | None = None,
        feature_schema_version: str | None = None,
        include_legacy: bool = True,
    ) -> list[BotVersion]:
        with self._lock:
            rows = list(self._bots.values())

        filtered: list[BotVersion] = []
        for row in rows:
            if ruleset_id and row.ruleset_id != ruleset_id:
                continue
            if policy_type and row.policy_type != policy_type:
                continue
            if feature_schema_version and row.feature_schema_version != feature_schema_version:
                continue
            if not include_legacy and "legacy" in row.tags:
                continue
            filtered.append(row)

        filtered.sort(key=lambda item: item.created_at, reverse=True)
        return filtered

    def get_bot(self, bot_version_id: str) -> BotVersion:
        with self._lock:
            bot = self._bots.get(bot_version_id)
            if bot is None:
                raise KeyError(f"Unknown bot_version_id={bot_version_id}")
            return bot

    def ensure_bot(
        self,
        *,
        bot_version_id: str,
        ruleset_id: str,
        policy_type: str,
        feature_schema_version: str,
        lookahead_policy_version: str,
        weights: dict[str, float],
        tags: set[str] | None = None,
    ) -> BotVersion:
        get_ruleset(ruleset_id)
        with self._lock:
            existing = self._bots.get(bot_version_id)
            if existing is not None:
                if existing.ruleset_id != ruleset_id:
                    raise ValueError(
                        f"bot_version_id={bot_version_id} already bound to ruleset_id={existing.ruleset_id}"
                    )
                return existing

            created = BotVersion(
                bot_version_id=bot_version_id,
                ruleset_id=ruleset_id,
                policy_type=policy_type,
                feature_schema_version=feature_schema_version,
                lookahead_policy_version=lookahead_policy_version,
                weights=normalize_weights(weights),
                source_job_id=None,
                source_checkpoint_id=None,
                tags=set(tags or set()),
            )
            self._bots[bot_version_id] = created
            if self._store is not None:
                self._store.upsert_bot_version(created)
            return created

    def create_from_checkpoint(
        self,
        *,
        bot_version_id: str,
        ruleset_id: str,
        checkpoint: TrainingCheckpoint | None,
        weights: dict[str, float],
        policy_type: str,
        feature_schema_version: str,
        lookahead_policy_version: str,
    ) -> BotVersion:
        get_ruleset(ruleset_id)

        with self._lock:
            if bot_version_id in self._bots:
                raise ValueError(f"bot_version_id already exists: {bot_version_id}")

            created = BotVersion(
                bot_version_id=bot_version_id,
                ruleset_id=ruleset_id,
                policy_type=policy_type,
                feature_schema_version=feature_schema_version,
                lookahead_policy_version=lookahead_policy_version,
                weights=normalize_weights(weights),
                source_job_id=checkpoint.job_id if checkpoint is not None else None,
                source_checkpoint_id=checkpoint.checkpoint_id if checkpoint is not None else None,
                tags=set(),
            )
            self._bots[created.bot_version_id] = created
            if self._store is not None:
                self._store.upsert_bot_version(created)
            return created

    def update_labels(
        self,
        bot_version_id: str,
        *,
        is_baseline: bool | None = None,
        is_league: bool | None = None,
        is_legacy: bool | None = None,
    ) -> BotVersion:
        with self._lock:
            current = self._bots.get(bot_version_id)
            if current is None:
                raise KeyError(f"Unknown bot_version_id={bot_version_id}")

            tags = set(current.tags)
            if is_baseline is not None:
                if is_baseline:
                    tags.add("baseline")
                else:
                    tags.discard("baseline")
            if is_league is not None:
                if is_league:
                    tags.add("league")
                else:
                    tags.discard("league")
            if is_legacy is not None:
                if is_legacy:
                    tags.add("legacy")
                else:
                    tags.discard("legacy")

            updated = replace(current, tags=tags)
            self._bots[bot_version_id] = updated
            if self._store is not None:
                self._store.upsert_bot_version(updated)
            return updated
