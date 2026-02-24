import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from app.bots.models import BotVersion
from app.league.models import LeagueRating, LeagueSeason, MatchRecord
from app.trainer.models import TrainingCheckpoint


class SQLiteStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS bot_versions (
                    bot_version_id TEXT PRIMARY KEY,
                    ruleset_id TEXT NOT NULL,
                    policy_type TEXT NOT NULL,
                    feature_schema_version TEXT NOT NULL,
                    lookahead_policy_version TEXT NOT NULL,
                    weights_json TEXT NOT NULL,
                    source_job_id TEXT,
                    source_checkpoint_id TEXT,
                    tags_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS league_ratings (
                    ruleset_id TEXT NOT NULL,
                    bot_version_id TEXT NOT NULL,
                    pool_type TEXT NOT NULL,
                    mu REAL NOT NULL,
                    sigma REAL NOT NULL,
                    matches_played INTEGER NOT NULL,
                    wins INTEGER NOT NULL,
                    losses INTEGER NOT NULL,
                    draws INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (ruleset_id, bot_version_id)
                );

                CREATE TABLE IF NOT EXISTS league_matches (
                    id TEXT PRIMARY KEY,
                    ruleset_id TEXT NOT NULL,
                    season_id TEXT,
                    bot_a_id TEXT NOT NULL,
                    bot_b_id TEXT NOT NULL,
                    winner_id TEXT,
                    played_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS league_seasons (
                    id TEXT PRIMARY KEY,
                    ruleset_id TEXT NOT NULL,
                    lifecycle_state TEXT NOT NULL,
                    seed INTEGER NOT NULL,
                    max_matches INTEGER NOT NULL,
                    microbatch_size INTEGER NOT NULL,
                    matches_done INTEGER NOT NULL,
                    stop_reason TEXT,
                    pair_cursor INTEGER NOT NULL,
                    pause_requested INTEGER NOT NULL,
                    stop_requested INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS training_jobs (
                    id TEXT PRIMARY KEY,
                    ruleset_id TEXT NOT NULL,
                    lifecycle_state TEXT NOT NULL,
                    stage_state TEXT,
                    profile_id TEXT,
                    seed_bot_version_id TEXT,
                    seed INTEGER NOT NULL,
                    params_json TEXT NOT NULL,
                    progress_json TEXT NOT NULL,
                    current_weights_json TEXT NOT NULL,
                    best_weights_json TEXT NOT NULL,
                    stop_reason TEXT
                );

                CREATE TABLE IF NOT EXISTS training_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    batches_done INTEGER NOT NULL,
                    games_played INTEGER NOT NULL,
                    best_score REAL NOT NULL,
                    stage_state TEXT
                );
                """
            )

    @staticmethod
    def _dumps(payload: Any) -> str:
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))

    @staticmethod
    def _loads(text: str) -> Any:
        return json.loads(text)

    def load_bot_versions(self) -> list[BotVersion]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT bot_version_id, ruleset_id, policy_type, feature_schema_version,
                       lookahead_policy_version, weights_json, source_job_id,
                       source_checkpoint_id, tags_json, created_at
                FROM bot_versions
                """
            ).fetchall()
        return [
            BotVersion(
                bot_version_id=row["bot_version_id"],
                ruleset_id=row["ruleset_id"],
                policy_type=row["policy_type"],
                feature_schema_version=row["feature_schema_version"],
                lookahead_policy_version=row["lookahead_policy_version"],
                weights=dict(self._loads(row["weights_json"])),
                source_job_id=row["source_job_id"],
                source_checkpoint_id=row["source_checkpoint_id"],
                tags=set(self._loads(row["tags_json"])),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def upsert_bot_version(self, bot: BotVersion) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO bot_versions (
                    bot_version_id, ruleset_id, policy_type, feature_schema_version,
                    lookahead_policy_version, weights_json, source_job_id,
                    source_checkpoint_id, tags_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bot_version_id) DO UPDATE SET
                    ruleset_id=excluded.ruleset_id,
                    policy_type=excluded.policy_type,
                    feature_schema_version=excluded.feature_schema_version,
                    lookahead_policy_version=excluded.lookahead_policy_version,
                    weights_json=excluded.weights_json,
                    source_job_id=excluded.source_job_id,
                    source_checkpoint_id=excluded.source_checkpoint_id,
                    tags_json=excluded.tags_json,
                    created_at=excluded.created_at
                """,
                (
                    bot.bot_version_id,
                    bot.ruleset_id,
                    bot.policy_type,
                    bot.feature_schema_version,
                    bot.lookahead_policy_version,
                    self._dumps(bot.weights),
                    bot.source_job_id,
                    bot.source_checkpoint_id,
                    self._dumps(sorted(bot.tags)),
                    bot.created_at,
                ),
            )

    def load_league_ratings(self) -> list[LeagueRating]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ruleset_id, bot_version_id, pool_type, mu, sigma, matches_played,
                       wins, losses, draws, updated_at
                FROM league_ratings
                """
            ).fetchall()
        return [
            LeagueRating(
                ruleset_id=row["ruleset_id"],
                bot_version_id=row["bot_version_id"],
                pool_type=row["pool_type"],
                mu=row["mu"],
                sigma=row["sigma"],
                matches_played=row["matches_played"],
                wins=row["wins"],
                losses=row["losses"],
                draws=row["draws"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def upsert_league_rating(self, rating: LeagueRating) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO league_ratings (
                    ruleset_id, bot_version_id, pool_type, mu, sigma, matches_played,
                    wins, losses, draws, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ruleset_id, bot_version_id) DO UPDATE SET
                    pool_type=excluded.pool_type,
                    mu=excluded.mu,
                    sigma=excluded.sigma,
                    matches_played=excluded.matches_played,
                    wins=excluded.wins,
                    losses=excluded.losses,
                    draws=excluded.draws,
                    updated_at=excluded.updated_at
                """,
                (
                    rating.ruleset_id,
                    rating.bot_version_id,
                    rating.pool_type,
                    rating.mu,
                    rating.sigma,
                    rating.matches_played,
                    rating.wins,
                    rating.losses,
                    rating.draws,
                    rating.updated_at,
                ),
            )

    def load_league_matches(self) -> list[MatchRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, ruleset_id, season_id, bot_a_id, bot_b_id, winner_id, played_at
                FROM league_matches
                ORDER BY played_at ASC
                """
            ).fetchall()
        return [
            MatchRecord(
                id=row["id"],
                ruleset_id=row["ruleset_id"],
                season_id=row["season_id"],
                bot_a_id=row["bot_a_id"],
                bot_b_id=row["bot_b_id"],
                winner_id=row["winner_id"],
                played_at=row["played_at"],
            )
            for row in rows
        ]

    def insert_league_match(self, match: MatchRecord) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO league_matches (
                    id, ruleset_id, season_id, bot_a_id, bot_b_id, winner_id, played_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    match.id,
                    match.ruleset_id,
                    match.season_id,
                    match.bot_a_id,
                    match.bot_b_id,
                    match.winner_id,
                    match.played_at,
                ),
            )

    def load_league_seasons(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, ruleset_id, lifecycle_state, seed, max_matches, microbatch_size,
                       matches_done, stop_reason, pair_cursor, pause_requested, stop_requested
                FROM league_seasons
                """
            ).fetchall()
        return [
            {
                "id": row["id"],
                "ruleset_id": row["ruleset_id"],
                "lifecycle_state": row["lifecycle_state"],
                "seed": row["seed"],
                "max_matches": row["max_matches"],
                "microbatch_size": row["microbatch_size"],
                "matches_done": row["matches_done"],
                "stop_reason": row["stop_reason"],
                "pair_cursor": row["pair_cursor"],
                "pause_requested": bool(row["pause_requested"]),
                "stop_requested": bool(row["stop_requested"]),
            }
            for row in rows
        ]

    def upsert_league_season(
        self,
        season: LeagueSeason,
        *,
        pair_cursor: int,
        pause_requested: bool,
        stop_requested: bool,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO league_seasons (
                    id, ruleset_id, lifecycle_state, seed, max_matches, microbatch_size,
                    matches_done, stop_reason, pair_cursor, pause_requested, stop_requested
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    ruleset_id=excluded.ruleset_id,
                    lifecycle_state=excluded.lifecycle_state,
                    seed=excluded.seed,
                    max_matches=excluded.max_matches,
                    microbatch_size=excluded.microbatch_size,
                    matches_done=excluded.matches_done,
                    stop_reason=excluded.stop_reason,
                    pair_cursor=excluded.pair_cursor,
                    pause_requested=excluded.pause_requested,
                    stop_requested=excluded.stop_requested
                """,
                (
                    season.id,
                    season.ruleset_id,
                    season.lifecycle_state,
                    season.seed,
                    season.max_matches,
                    season.microbatch_size,
                    season.matches_done,
                    season.stop_reason,
                    pair_cursor,
                    1 if pause_requested else 0,
                    1 if stop_requested else 0,
                ),
            )

    def load_training_jobs(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, ruleset_id, lifecycle_state, stage_state, profile_id, seed_bot_version_id,
                       seed, params_json, progress_json, current_weights_json, best_weights_json, stop_reason
                FROM training_jobs
                """
            ).fetchall()
        return [
            {
                "id": row["id"],
                "ruleset_id": row["ruleset_id"],
                "lifecycle_state": row["lifecycle_state"],
                "stage_state": row["stage_state"],
                "profile_id": row["profile_id"],
                "seed_bot_version_id": row["seed_bot_version_id"],
                "seed": row["seed"],
                "params": self._loads(row["params_json"]),
                "progress": self._loads(row["progress_json"]),
                "current_weights": self._loads(row["current_weights_json"]),
                "best_weights": self._loads(row["best_weights_json"]),
                "stop_reason": row["stop_reason"],
            }
            for row in rows
        ]

    def upsert_training_job(self, payload: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO training_jobs (
                    id, ruleset_id, lifecycle_state, stage_state, profile_id, seed_bot_version_id,
                    seed, params_json, progress_json, current_weights_json, best_weights_json, stop_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    ruleset_id=excluded.ruleset_id,
                    lifecycle_state=excluded.lifecycle_state,
                    stage_state=excluded.stage_state,
                    profile_id=excluded.profile_id,
                    seed_bot_version_id=excluded.seed_bot_version_id,
                    seed=excluded.seed,
                    params_json=excluded.params_json,
                    progress_json=excluded.progress_json,
                    current_weights_json=excluded.current_weights_json,
                    best_weights_json=excluded.best_weights_json,
                    stop_reason=excluded.stop_reason
                """,
                (
                    payload["id"],
                    payload["ruleset_id"],
                    payload["lifecycle_state"],
                    payload.get("stage_state"),
                    payload.get("profile_id"),
                    payload.get("seed_bot_version_id"),
                    payload["seed"],
                    self._dumps(payload["params"]),
                    self._dumps(payload["progress"]),
                    self._dumps(payload["current_weights"]),
                    self._dumps(payload["best_weights"]),
                    payload.get("stop_reason"),
                ),
            )

    def load_training_checkpoints(self) -> list[TrainingCheckpoint]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT checkpoint_id, job_id, path, batches_done, games_played, best_score, stage_state
                FROM training_checkpoints
                ORDER BY batches_done ASC
                """
            ).fetchall()
        return [
            TrainingCheckpoint(
                checkpoint_id=row["checkpoint_id"],
                job_id=row["job_id"],
                path=row["path"],
                batches_done=row["batches_done"],
                games_played=row["games_played"],
                best_score=row["best_score"],
                stage_state=row["stage_state"],
            )
            for row in rows
        ]

    def upsert_training_checkpoint(self, checkpoint: TrainingCheckpoint) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO training_checkpoints (
                    checkpoint_id, job_id, path, batches_done, games_played, best_score, stage_state
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(checkpoint_id) DO UPDATE SET
                    job_id=excluded.job_id,
                    path=excluded.path,
                    batches_done=excluded.batches_done,
                    games_played=excluded.games_played,
                    best_score=excluded.best_score,
                    stage_state=excluded.stage_state
                """,
                (
                    checkpoint.checkpoint_id,
                    checkpoint.job_id,
                    checkpoint.path,
                    checkpoint.batches_done,
                    checkpoint.games_played,
                    checkpoint.best_score,
                    checkpoint.stage_state,
                ),
            )
