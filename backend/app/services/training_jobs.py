import threading
import time
import math
import json
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
import random
from uuid import uuid4

from app.bots.policy import normalize_weights
from app.bots.selfplay import SelfPlaySimulator, play_strong_vs
from app.rulesets import get_ruleset
from app.services.bot_catalog import BotCatalogService
from app.services.events import EventBus
from app.services.league import LeagueService
from app.storage import SQLiteStore
from app.trainer import CheckpointStore, TrainingCheckpoint, TrainingParams, TrainingProgress
from app.trainer.models import LifecycleState, StageState


@dataclass(slots=True)
class TrainingJob:
    id: str
    ruleset_id: str
    lifecycle_state: LifecycleState
    stage_state: StageState | None
    profile_id: str | None
    seed_bot_version_id: str | None
    seed: int
    params: TrainingParams
    progress: TrainingProgress
    current_weights: dict[str, float]
    best_weights: dict[str, float]
    stop_reason: str | None = None


@dataclass(slots=True)
class _TrainingRuntime:
    thread: threading.Thread | None = None
    run_gate: threading.Event = field(default_factory=threading.Event)
    pause_requested: bool = False
    stop_requested: bool = False
    simulator: SelfPlaySimulator | None = None
    last_auto_promote_window: int = 0


@dataclass(frozen=True, slots=True)
class _StrictnessConfig:
    level: int
    quality_gate_games: int
    min_winrate: float
    min_lcb: float
    top_k_opponents: int
    league_only: bool
    dual_seed: bool


class TrainingJobService:
    _TOP_K_OPPONENTS = 16
    _PROMOTE_EVERY_WINDOWS = 4
    _STRICTNESS_LEVELS: tuple[_StrictnessConfig, ...] = (
        _StrictnessConfig(0, 256, 0.57, 0.53, 16, False, False),
        _StrictnessConfig(1, 384, 0.60, 0.56, 16, False, False),
        _StrictnessConfig(2, 512, 0.62, 0.58, 16, True, False),
        _StrictnessConfig(3, 768, 0.64, 0.60, 16, True, True),
    )

    def __init__(
        self,
        event_bus: EventBus,
        checkpoint_root: Path | None = None,
        bot_catalog: BotCatalogService | None = None,
        league_service: LeagueService | None = None,
        store: SQLiteStore | None = None,
    ) -> None:
        self._jobs: dict[str, TrainingJob] = {}
        self._event_bus = event_bus
        self._checkpoints: dict[str, list[TrainingCheckpoint]] = {}
        self._runtimes: dict[str, _TrainingRuntime] = {}
        self._bot_catalog = bot_catalog
        self._league_service = league_service
        self._store = store
        self._lock = threading.RLock()
        root = checkpoint_root or (Path.cwd() / ".data" / "training_checkpoints")
        self._checkpoint_store = CheckpointStore(root)
        self._restore_from_store()

    def _restore_from_store(self) -> None:
        if self._store is None:
            return

        with self._lock:
            jobs = self._store.load_training_jobs()
            for row in jobs:
                progress_payload = row["progress"]
                progress = TrainingProgress(
                    games_played=int(progress_payload.get("games_played", 0)),
                    batches_done=int(progress_payload.get("batches_done", 0)),
                    windows_done=int(progress_payload.get("windows_done", 0)),
                    best_score=float(progress_payload.get("best_score", 0.0)),
                    last_score=float(progress_payload.get("last_score", 0.0)),
                    plateau_windows=int(progress_payload.get("plateau_windows", 0)),
                    candidate_streak=int(progress_payload.get("candidate_streak", 0)),
                    stage_enter_window=int(progress_payload.get("stage_enter_window", 0)),
                    cycle_index=int(progress_payload.get("cycle_index", 0)),
                    strictness_level=int(progress_payload.get("strictness_level", 0)),
                    meta_plateau_counter=int(progress_payload.get("meta_plateau_counter", 0)),
                    champion_gate_lcb=float(progress_payload.get("champion_gate_lcb", 0.0)),
                    eval_protocol_hash=str(progress_payload.get("eval_protocol_hash", "")),
                )
                state = row["lifecycle_state"]
                if state in {"Running", "Pausing", "Stopping"}:
                    state = "Paused"

                job = TrainingJob(
                    id=row["id"],
                    ruleset_id=row["ruleset_id"],
                    lifecycle_state=state,
                    stage_state=row["stage_state"],
                    profile_id=row["profile_id"],
                    seed_bot_version_id=row["seed_bot_version_id"],
                    seed=int(row["seed"]),
                    params=TrainingParams(**row["params"]),
                    progress=progress,
                    current_weights=normalize_weights(row["current_weights"]),
                    best_weights=normalize_weights(row["best_weights"]),
                    stop_reason=row["stop_reason"],
                )
                self._jobs[job.id] = job
                self._checkpoints[job.id] = []
                self._runtimes[job.id] = _TrainingRuntime(
                    simulator=SelfPlaySimulator(
                        ruleset_id=job.ruleset_id,
                        seed=job.seed + job.progress.windows_done,
                        window_games=job.params.microbatch_size * job.params.eval_window_batches,
                        population_size=job.params.population_size,
                        train_split=job.params.train_split,
                        worker_count=job.params.worker_count,
                        seed_weights=job.current_weights,
                    ),
                    last_auto_promote_window=job.progress.windows_done,
                )
                if not job.progress.eval_protocol_hash:
                    job.progress.eval_protocol_hash = self._compute_eval_protocol_hash(job)
                self._persist_job_locked(job)

            for checkpoint in self._store.load_training_checkpoints():
                if checkpoint.job_id in self._jobs:
                    self._checkpoints.setdefault(checkpoint.job_id, []).append(checkpoint)

            for checkpoint_list in self._checkpoints.values():
                checkpoint_list.sort(key=lambda item: item.batches_done)

    def _persist_job_locked(self, job: TrainingJob) -> None:
        if self._store is None:
            return
        self._store.upsert_training_job(
            {
                "id": job.id,
                "ruleset_id": job.ruleset_id,
                "lifecycle_state": job.lifecycle_state,
                "stage_state": job.stage_state,
                "profile_id": job.profile_id,
                "seed_bot_version_id": job.seed_bot_version_id,
                "seed": job.seed,
                "params": {
                    "microbatch_size": job.params.microbatch_size,
                    "eval_window_batches": job.params.eval_window_batches,
                    "checkpoint_interval_batches": job.params.checkpoint_interval_batches,
                    "population_size": job.params.population_size,
                    "train_split": job.params.train_split,
                    "worker_count": job.params.worker_count,
                    "quality_gate_games": job.params.quality_gate_games,
                    "quality_gate_min_winrate": job.params.quality_gate_min_winrate,
                    "quality_gate_min_lower_bound": job.params.quality_gate_min_lower_bound,
                    "target_score": job.params.target_score,
                    "improvement_delta": job.params.improvement_delta,
                    "plateau_delta": job.params.plateau_delta,
                    "plateau_patience_windows": job.params.plateau_patience_windows,
                    "early_stop_plateau_windows": job.params.early_stop_plateau_windows,
                    "min_windows_before_early_stop": job.params.min_windows_before_early_stop,
                    "tick_delay_ms": job.params.tick_delay_ms,
                    "autoevolve_enabled": job.params.autoevolve_enabled,
                    "meta_plateau_patience_cycles": job.params.meta_plateau_patience_cycles,
                    "strictness_max_level": job.params.strictness_max_level,
                },
                "progress": {
                    "games_played": job.progress.games_played,
                    "batches_done": job.progress.batches_done,
                    "windows_done": job.progress.windows_done,
                    "best_score": job.progress.best_score,
                    "last_score": job.progress.last_score,
                    "plateau_windows": job.progress.plateau_windows,
                    "candidate_streak": job.progress.candidate_streak,
                    "stage_enter_window": job.progress.stage_enter_window,
                    "cycle_index": job.progress.cycle_index,
                    "strictness_level": job.progress.strictness_level,
                    "meta_plateau_counter": job.progress.meta_plateau_counter,
                    "champion_gate_lcb": job.progress.champion_gate_lcb,
                    "eval_protocol_hash": job.progress.eval_protocol_hash,
                },
                "current_weights": dict(job.current_weights),
                "best_weights": dict(job.best_weights),
                "stop_reason": job.stop_reason,
            }
        )

    def create_job(
        self,
        ruleset_id: str,
        profile_id: str | None,
        seed_bot_version_id: str | None = None,
        seed: int | None = None,
        seed_weights: dict[str, float] | None = None,
        params: TrainingParams | None = None,
    ) -> TrainingJob:
        get_ruleset(ruleset_id)
        resolved_params = params or TrainingParams()
        resolved_seed = seed if seed is not None else 0
        normalized_seed_weights = normalize_weights(seed_weights)
        job = TrainingJob(
            id=str(uuid4()),
            ruleset_id=ruleset_id,
            lifecycle_state="Idle",
            stage_state=None,
            profile_id=profile_id,
            seed_bot_version_id=seed_bot_version_id,
            seed=resolved_seed,
            params=resolved_params,
            progress=TrainingProgress(),
            current_weights=dict(normalized_seed_weights),
            best_weights=dict(normalized_seed_weights),
        )
        job.progress.eval_protocol_hash = self._compute_eval_protocol_hash(job)
        with self._lock:
            self._jobs[job.id] = job
            self._checkpoints[job.id] = []
            self._runtimes[job.id] = _TrainingRuntime(
                simulator=SelfPlaySimulator(
                    ruleset_id=ruleset_id,
                    seed=resolved_seed,
                    window_games=resolved_params.microbatch_size * resolved_params.eval_window_batches,
                    population_size=resolved_params.population_size,
                    train_split=resolved_params.train_split,
                    worker_count=resolved_params.worker_count,
                    seed_weights=normalized_seed_weights,
                )
            )
            self._persist_job_locked(job)
        return job

    def get_job(self, job_id: str) -> TrainingJob:
        with self._lock:
            try:
                return self._jobs[job_id]
            except KeyError as exc:
                raise KeyError(f"Unknown training job id={job_id}") from exc

    def list_checkpoints(self, job_id: str) -> list[TrainingCheckpoint]:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(f"Unknown training job id={job_id}")
            return list(self._checkpoints.get(job_id, []))

    def list_all_checkpoints(self, ruleset_id: str | None = None) -> list[tuple[TrainingJob, TrainingCheckpoint]]:
        with self._lock:
            rows: list[tuple[TrainingJob, TrainingCheckpoint]] = []
            for job_id, job in self._jobs.items():
                if ruleset_id is not None and job.ruleset_id != ruleset_id:
                    continue
                for checkpoint in self._checkpoints.get(job_id, []):
                    rows.append((job, checkpoint))
            return rows

    def get_checkpoint_payload(self, job_id: str, checkpoint_id: str) -> dict:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(f"Unknown training job id={job_id}")
            checkpoint = self._get_checkpoint_locked(job_id, checkpoint_id)
            return self._checkpoint_store.load(checkpoint)

    async def load_checkpoint(self, job_id: str, checkpoint_id: str) -> TrainingJob:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(f"Unknown training job id={job_id}")
            if job.lifecycle_state in {"Running", "Pausing", "Stopping"}:
                raise ValueError("Cannot load checkpoint while job is active")

            checkpoint = self._get_checkpoint_locked(job_id, checkpoint_id)
            payload = self._checkpoint_store.load(checkpoint)

            job.progress.batches_done = int(payload["batches_done"])
            job.progress.games_played = int(payload["games_played"])
            job.progress.best_score = float(payload["best_score"])
            job.progress.last_score = float(payload["best_score"])
            job.progress.windows_done = job.progress.batches_done // job.params.eval_window_batches
            job.progress.plateau_windows = 0
            job.progress.candidate_streak = 0
            stage_state = payload.get("stage_state")
            job.stage_state = stage_state if stage_state else None
            job.current_weights = normalize_weights(payload.get("current_weights"))
            job.best_weights = normalize_weights(payload.get("best_weights"))

            runtime = self._runtimes[job.id]
            if runtime.simulator is not None:
                runtime.simulator.close()
            runtime.simulator = SelfPlaySimulator(
                ruleset_id=job.ruleset_id,
                seed=job.seed + job.progress.windows_done,
                window_games=job.params.microbatch_size * job.params.eval_window_batches,
                population_size=job.params.population_size,
                train_split=job.params.train_split,
                worker_count=job.params.worker_count,
                seed_weights=job.current_weights,
            )
            self._persist_job_locked(job)

        self._event_bus.publish_sync(
            event_type="training.checkpoint_loaded",
            entity_id=job_id,
            ruleset_id=job.ruleset_id,
            payload={"checkpoint_id": checkpoint_id, "batches_done": job.progress.batches_done},
        )
        return job

    async def apply_command(self, job_id: str, command: str) -> TrainingJob:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(f"Unknown training job id={job_id}")
            runtime = self._runtimes[job_id]

            if command == "start":
                self._ensure_state(job, {"Idle"}, command)
                old_stage = job.stage_state
                if job.stage_state is None:
                    self._set_stage_locked(job, "Warmup", reason="job_started", publish_async=False)
                self._ensure_league_bootstrap_locked(job)
                self._set_state_locked(job, "Running", publish_async=False)
                runtime.pause_requested = False
                runtime.stop_requested = False
                runtime.run_gate.set()
                if runtime.thread is None or not runtime.thread.is_alive():
                    runtime.thread = threading.Thread(
                        target=self._run_loop,
                        args=(job.id,),
                        daemon=True,
                        name=f"trainer-{job.id[:8]}",
                    )
                    runtime.thread.start()
                if old_stage != job.stage_state:
                    self._event_bus.publish_sync(
                        event_type="training.stage_changed",
                        entity_id=job.id,
                        ruleset_id=job.ruleset_id,
                        payload={"old_stage": old_stage, "stage_state": job.stage_state, "reason": "job_started"},
                    )
                self._event_bus.publish_sync(
                    event_type="job.lifecycle_changed",
                    entity_id=job.id,
                    ruleset_id=job.ruleset_id,
                    payload={"old_state": "Idle", "new_state": "Running"},
                )
                return job

            if command == "pause":
                self._ensure_state(job, {"Running"}, command)
                runtime.pause_requested = True
                old = job.lifecycle_state
                job.lifecycle_state = "Pausing"
                self._persist_job_locked(job)
                self._event_bus.publish_sync(
                    event_type="job.lifecycle_changed",
                    entity_id=job.id,
                    ruleset_id=job.ruleset_id,
                    payload={"old_state": old, "new_state": "Pausing"},
                )
                return job

            if command == "resume":
                self._ensure_state(job, {"Paused"}, command)
                runtime.pause_requested = False
                old = job.lifecycle_state
                job.lifecycle_state = "Running"
                runtime.run_gate.set()
                self._persist_job_locked(job)
                self._event_bus.publish_sync(
                    event_type="job.lifecycle_changed",
                    entity_id=job.id,
                    ruleset_id=job.ruleset_id,
                    payload={"old_state": old, "new_state": "Running"},
                )
                return job

            if command == "stop":
                self._ensure_state(job, {"Running", "Pausing", "Paused"}, command)
                runtime.stop_requested = True
                job.stop_reason = "stopped_by_user"
                old = job.lifecycle_state
                job.lifecycle_state = "Stopping"
                self._persist_job_locked(job)
                self._event_bus.publish_sync(
                    event_type="job.lifecycle_changed",
                    entity_id=job.id,
                    ruleset_id=job.ruleset_id,
                    payload={"old_state": old, "new_state": "Stopping"},
                )

                if old == "Paused":
                    self._set_stage_locked(job, "Finished", reason=job.stop_reason)
                    self._set_state_locked(job, "Stopped")
                    runtime.run_gate.clear()
                    if runtime.simulator is not None:
                        runtime.simulator.close()
                else:
                    runtime.run_gate.set()
                return job

        raise ValueError(f"Unknown command: {command}")

    def _run_loop(self, job_id: str) -> None:
        while True:
            with self._lock:
                job = self._jobs[job_id]
                runtime = self._runtimes[job_id]
                state = job.lifecycle_state

            if state in {"Stopped", "Completed", "Error"}:
                with self._lock:
                    runtime = self._runtimes[job_id]
                    if runtime.simulator is not None:
                        runtime.simulator.close()
                return

            runtime.run_gate.wait()

            with self._lock:
                job = self._jobs[job_id]
                runtime = self._runtimes[job_id]

                if runtime.stop_requested and job.lifecycle_state == "Stopping":
                    self._set_stage_locked(job, "Finished", reason=job.stop_reason or "stopped")
                    self._set_state_locked(job, "Stopped")
                    runtime.run_gate.clear()
                    if runtime.simulator is not None:
                        runtime.simulator.close()
                    return

                if job.lifecycle_state == "Pausing":
                    runtime.run_gate.clear()
                    self._set_state_locked(job, "Paused")
                    continue

                if job.lifecycle_state != "Running":
                    continue

                tick_delay_ms = job.params.tick_delay_ms

            # Keep sleep outside the critical section so command handlers
            # can acquire the lock and apply pause/stop promptly.
            if tick_delay_ms:
                time.sleep(tick_delay_ms / 1000)

            with self._lock:
                job = self._jobs[job_id]
                runtime = self._runtimes[job_id]

                if runtime.stop_requested and job.lifecycle_state == "Stopping":
                    self._set_stage_locked(job, "Finished", reason=job.stop_reason or "stopped")
                    self._set_state_locked(job, "Stopped")
                    runtime.run_gate.clear()
                    if runtime.simulator is not None:
                        runtime.simulator.close()
                    return

                if job.lifecycle_state == "Pausing":
                    runtime.run_gate.clear()
                    self._set_state_locked(job, "Paused")
                    continue

                if job.lifecycle_state != "Running":
                    continue

                try:
                    self._run_microbatch_locked(job, runtime)
                except Exception as exc:
                    job.stop_reason = f"runtime_error: {exc}"
                    self._set_stage_locked(job, "Finished", reason="runtime_error")
                    self._set_state_locked(job, "Error")
                    runtime.run_gate.clear()
                    if runtime.simulator is not None:
                        runtime.simulator.close()
                    return

                if runtime.stop_requested:
                    self._set_stage_locked(job, "Finished", reason=job.stop_reason or "stopped")
                    self._set_state_locked(job, "Stopped")
                    runtime.run_gate.clear()
                    if runtime.simulator is not None:
                        runtime.simulator.close()
                    return

                if runtime.pause_requested:
                    runtime.run_gate.clear()
                    self._set_state_locked(job, "Paused")
                    continue

                if self._should_finish_locked(job):
                    self._set_stage_locked(job, "Finished", reason=job.stop_reason or "completed")
                    self._set_state_locked(job, "Completed")
                    runtime.run_gate.clear()
                    if runtime.simulator is not None:
                        runtime.simulator.close()
                    return

            time.sleep(0.0005)

    def _run_microbatch_locked(self, job: TrainingJob, runtime: _TrainingRuntime) -> None:
        job.progress.batches_done += 1
        job.progress.games_played += job.params.microbatch_size
        wr_baseline: float | None = None
        wr_active: float | None = None
        avg_turns_win: float | None = None
        strictness = self._strictness_config_for_job(job)

        if job.progress.batches_done % job.params.eval_window_batches == 0:
            if runtime.simulator is None:
                runtime.simulator = SelfPlaySimulator(
                    ruleset_id=job.ruleset_id,
                    seed=job.seed + job.progress.windows_done,
                    window_games=job.params.microbatch_size * job.params.eval_window_batches,
                    population_size=job.params.population_size,
                    train_split=job.params.train_split,
                    worker_count=job.params.worker_count,
                    seed_weights=job.current_weights,
                )

            league_opponents = self._collect_top_league_opponents_locked(job, strictness)
            metrics = runtime.simulator.next_window(job.progress.windows_done, league_opponents=league_opponents)
            prev_best = job.progress.best_score
            job.progress.windows_done += 1
            job.progress.last_score = metrics.score
            wr_baseline = metrics.wr_baseline
            wr_active = metrics.wr_active
            avg_turns_win = metrics.avg_turns_win

            if metrics.score > prev_best:
                job.progress.best_score = metrics.score

            if metrics.score - prev_best >= job.params.improvement_delta:
                job.progress.candidate_streak += 1
            else:
                job.progress.candidate_streak = 0

            if metrics.score - prev_best < job.params.plateau_delta:
                job.progress.plateau_windows += 1
            else:
                job.progress.plateau_windows = 0

            job.current_weights = runtime.simulator.current_weights
            job.best_weights = runtime.simulator.best_weights

            self._apply_stage_transitions_locked(job)

        self._event_bus.publish_sync(
            event_type="training.metrics",
            entity_id=job.id,
            ruleset_id=job.ruleset_id,
            payload={
                "batches_done": job.progress.batches_done,
                "games_played": job.progress.games_played,
                "windows_done": job.progress.windows_done,
                "wr_baseline": wr_baseline,
                "wr_active": wr_active,
                "avg_turns_win": avg_turns_win,
                "score": job.progress.last_score,
                "best_score": job.progress.best_score,
                "plateau_windows": job.progress.plateau_windows,
                "window_evaluated": wr_baseline is not None,
                "cycle_index": job.progress.cycle_index,
                "strictness_level": job.progress.strictness_level,
                "meta_plateau_counter": job.progress.meta_plateau_counter,
                "champion_gate_lcb": job.progress.champion_gate_lcb,
                "eval_protocol_hash": job.progress.eval_protocol_hash,
            },
        )

        if job.progress.batches_done % job.params.checkpoint_interval_batches == 0:
            checkpoint = self._checkpoint_store.save(
                job_id=job.id,
                batches_done=job.progress.batches_done,
                games_played=job.progress.games_played,
                best_score=job.progress.best_score,
                stage_state=job.stage_state,
                current_weights=job.current_weights,
                best_weights=job.best_weights,
            )
            self._checkpoints[job.id].append(checkpoint)
            if self._store is not None:
                self._store.upsert_training_checkpoint(checkpoint)
            self._maybe_auto_promote_checkpoint_locked(job, runtime, checkpoint)
            self._event_bus.publish_sync(
                event_type="training.checkpoint_created",
                entity_id=job.id,
                ruleset_id=job.ruleset_id,
                payload={
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "batches_done": checkpoint.batches_done,
                    "path": checkpoint.path,
                },
            )
        self._persist_job_locked(job)

    def _ensure_league_bootstrap_locked(self, job: TrainingJob) -> None:
        if self._bot_catalog is None or self._league_service is None:
            return

        baseline_random = self._bot_catalog.ensure_bot(
            bot_version_id=f"{job.ruleset_id}-baseline-random",
            ruleset_id=job.ruleset_id,
            policy_type="random",
            feature_schema_version="classic_features_v1",
            lookahead_policy_version="off",
            weights={"hunt_heat": 0.2, "target_adjacent": 0.2},
            tags={"baseline"},
        )
        baseline_strong = self._bot_catalog.ensure_bot(
            bot_version_id=f"{job.ruleset_id}-baseline-strong",
            ruleset_id=job.ruleset_id,
            policy_type="probability_strong",
            feature_schema_version="classic_features_v1",
            lookahead_policy_version="adaptive_v1",
            weights=job.current_weights,
            tags={"baseline"},
        )

        self._league_service.register_bot(job.ruleset_id, baseline_random.bot_version_id, "baseline")
        self._league_service.register_bot(job.ruleset_id, baseline_strong.bot_version_id, "baseline")

        seed_bot_id = f"{job.id[:8]}-seed"
        seed_bot = self._bot_catalog.ensure_bot(
            bot_version_id=seed_bot_id,
            ruleset_id=job.ruleset_id,
            policy_type="probability_strong",
            feature_schema_version="classic_features_v1",
            lookahead_policy_version="adaptive_v1",
            weights=job.current_weights,
            tags={"active"},
        )
        self._league_service.register_bot(job.ruleset_id, seed_bot.bot_version_id, "active")

    def _collect_top_league_opponents_locked(
        self,
        job: TrainingJob,
        strictness: _StrictnessConfig,
    ) -> list[dict[str, float]]:
        if self._bot_catalog is None or self._league_service is None:
            return []

        try:
            table = self._league_service.list_table(job.ruleset_id)
        except KeyError:
            return []

        if strictness.league_only:
            rows = [row for row in table if row.pool_type == "league"][: strictness.top_k_opponents]
            if not rows:
                rows = [row for row in table if row.pool_type == "active"][: strictness.top_k_opponents]
        else:
            rows = [row for row in table if row.pool_type in {"league", "active", "baseline"}][
                : strictness.top_k_opponents
            ]

        opponents: list[dict[str, float]] = []
        for row in rows:
            try:
                bot = self._bot_catalog.get_bot(row.bot_version_id)
            except KeyError:
                continue
            opponents.append(dict(bot.weights))
        return opponents

    def _maybe_auto_promote_checkpoint_locked(
        self,
        job: TrainingJob,
        runtime: _TrainingRuntime,
        checkpoint: TrainingCheckpoint,
    ) -> None:
        if self._bot_catalog is None or self._league_service is None:
            return

        if (job.progress.windows_done - runtime.last_auto_promote_window) < self._PROMOTE_EVERY_WINDOWS:
            return
        runtime.last_auto_promote_window = job.progress.windows_done

        checkpoint_payload = self._checkpoint_store.load(checkpoint)
        weights = checkpoint_payload.get("best_weights") or checkpoint_payload.get("current_weights") or {}
        if not weights:
            return

        strictness = self._strictness_config_for_job(job)
        protocol_hash_before = job.progress.eval_protocol_hash
        if not protocol_hash_before:
            job.progress.eval_protocol_hash = self._compute_eval_protocol_hash(job)
            protocol_hash_before = job.progress.eval_protocol_hash

        before_signature = self._top16_signature_locked(job.ruleset_id)
        gate_lcb = float(job.progress.champion_gate_lcb)
        improved = False
        job.progress.cycle_index += 1

        gate = self._run_quality_gate_locked(job, normalize_weights(weights), strictness)
        gate_lcb = float(gate["lower_bound"])
        if not gate["passed"]:
            self._update_autoevolve_progress_locked(job, improved=False, gate_lcb=gate_lcb)
            self._event_bus.publish_sync(
                event_type="training.quality_gate_failed",
                entity_id=job.id,
                ruleset_id=job.ruleset_id,
                payload={
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "games": gate["games"],
                    "wins": gate["wins"],
                    "winrate": gate["winrate"],
                    "lower_bound": gate["lower_bound"],
                    "required_winrate": gate["required_winrate"],
                    "required_lower_bound": gate["required_lower_bound"],
                    "strictness_level": strictness.level,
                    "eval_protocol_hash": protocol_hash_before,
                    "cycle_index": job.progress.cycle_index,
                },
            )
            return

        bot_version_id = f"{job.id[:8]}-b{checkpoint.batches_done}"
        try:
            bot = self._bot_catalog.create_from_checkpoint(
                bot_version_id=bot_version_id,
                ruleset_id=job.ruleset_id,
                checkpoint=checkpoint,
                weights=weights,
                policy_type="probability_strong",
                feature_schema_version="classic_features_v1",
                lookahead_policy_version="adaptive_v1",
            )
        except ValueError:
            return

        runtime.last_auto_promote_window = job.progress.windows_done
        self._league_service.register_bot(job.ruleset_id, bot.bot_version_id, "active")
        self._event_bus.publish_sync(
            event_type="training.quality_gate_passed",
            entity_id=job.id,
            ruleset_id=job.ruleset_id,
            payload={
                "checkpoint_id": checkpoint.checkpoint_id,
                "bot_version_id": bot.bot_version_id,
                "games": gate["games"],
                "wins": gate["wins"],
                "winrate": gate["winrate"],
                "lower_bound": gate["lower_bound"],
            },
        )
        self._run_promotion_matches_locked(job, bot.bot_version_id, bot.weights)

        after_signature = self._top16_signature_locked(job.ruleset_id)
        improved = after_signature != before_signature or gate_lcb > (job.progress.champion_gate_lcb + 1e-6)
        self._update_autoevolve_progress_locked(job, improved=improved, gate_lcb=gate_lcb)

    def _run_promotion_matches_locked(self, job: TrainingJob, candidate_id: str, candidate_weights: dict[str, float]) -> None:
        if self._bot_catalog is None or self._league_service is None:
            return

        try:
            table = self._league_service.list_table(job.ruleset_id)
        except KeyError:
            return
        opponents = [
            row.bot_version_id
            for row in table
            if row.bot_version_id != candidate_id and row.pool_type in {"league", "baseline", "active"}
        ][: self._TOP_K_OPPONENTS]

        if not opponents:
            return

        try:
            ruleset = get_ruleset(job.ruleset_id)
        except KeyError:
            return
        for idx, opponent_id in enumerate(opponents):
            try:
                opponent = self._bot_catalog.get_bot(opponent_id)
            except KeyError:
                continue

            rng = random.Random(job.seed * 1000 + job.progress.windows_done * 37 + idx)
            result = play_strong_vs(
                ruleset,
                rng,
                strong_weights=candidate_weights,
                opponent_kind="strong",
                opponent_weights=opponent.weights,
                first_player=idx % 2,
            )
            winner_id = candidate_id if result.winner == 0 else opponent_id
            self._league_service.record_match(
                ruleset_id=job.ruleset_id,
                bot_a_id=candidate_id,
                bot_b_id=opponent_id,
                winner_id=winner_id,
            )

    def _run_quality_gate_locked(
        self,
        job: TrainingJob,
        candidate_weights: dict[str, float],
        strictness: _StrictnessConfig,
    ) -> dict[str, float | int | bool]:
        if self._bot_catalog is None or self._league_service is None:
            return {
                "passed": True,
                "games": 0,
                "wins": 0,
                "winrate": 1.0,
                "lower_bound": 1.0,
                "required_winrate": strictness.min_winrate,
                "required_lower_bound": strictness.min_lcb,
            }

        try:
            table = self._league_service.list_table(job.ruleset_id)
            ruleset = get_ruleset(job.ruleset_id)
        except KeyError:
            return {
                "passed": True,
                "games": 0,
                "wins": 0,
                "winrate": 1.0,
                "lower_bound": 1.0,
                "required_winrate": strictness.min_winrate,
                "required_lower_bound": strictness.min_lcb,
            }

        if strictness.league_only:
            opponents = [row.bot_version_id for row in table if row.pool_type == "league"][: strictness.top_k_opponents]
            if not opponents:
                opponents = [row.bot_version_id for row in table if row.pool_type == "active"][
                    : strictness.top_k_opponents
                ]
        else:
            opponents = [row.bot_version_id for row in table if row.pool_type in {"league", "baseline", "active"}][
                : strictness.top_k_opponents
            ]
        if not opponents:
            return {
                "passed": True,
                "games": 0,
                "wins": 0,
                "winrate": 1.0,
                "lower_bound": 1.0,
                "required_winrate": strictness.min_winrate,
                "required_lower_bound": strictness.min_lcb,
            }

        games = max(2, strictness.quality_gate_games)
        wins = 0
        total = 0
        seeds = [job.seed * 10_007 + job.progress.windows_done * 503]
        if strictness.dual_seed:
            seeds.append(job.seed * 20_011 + job.progress.windows_done * 709 + 131)

        for seed_index, base_seed in enumerate(seeds):
            for idx in range(games):
                opponent_id = opponents[idx % len(opponents)]
                try:
                    opponent = self._bot_catalog.get_bot(opponent_id)
                except KeyError:
                    continue

                rng = random.Random(base_seed + idx * 13 + seed_index * 9_973)
                result = play_strong_vs(
                    ruleset,
                    rng,
                    strong_weights=candidate_weights,
                    opponent_kind="strong",
                    opponent_weights=opponent.weights,
                    first_player=idx % 2,
                )
                total += 1
                if result.winner == 0:
                    wins += 1

        total = max(1, total)
        winrate = wins / total
        lower_bound = self._wilson_lower_bound(wins=wins, total=total)
        passed = (
            winrate >= strictness.min_winrate
            and lower_bound >= strictness.min_lcb
        )
        return {
            "passed": passed,
            "games": total,
            "wins": wins,
            "winrate": round(winrate, 6),
            "lower_bound": round(lower_bound, 6),
            "required_winrate": strictness.min_winrate,
            "required_lower_bound": strictness.min_lcb,
        }

    @staticmethod
    def _wilson_lower_bound(*, wins: int, total: int, z: float = 1.96) -> float:
        if total <= 0:
            return 0.0
        p = wins / total
        z2 = z * z
        denom = 1 + z2 / total
        center = p + z2 / (2 * total)
        margin = z * math.sqrt((p * (1 - p) + z2 / (4 * total)) / total)
        return max(0.0, (center - margin) / denom)

    def _strictness_config_for_job(self, job: TrainingJob) -> _StrictnessConfig:
        level = max(0, int(job.progress.strictness_level))
        max_level = min(int(job.params.strictness_max_level), len(self._STRICTNESS_LEVELS) - 1)
        level = min(level, max_level)

        base = self._STRICTNESS_LEVELS[level]
        base_games = max(2, int(job.params.quality_gate_games))
        min_winrate = max(0.0, float(job.params.quality_gate_min_winrate))
        min_lcb = max(0.0, float(job.params.quality_gate_min_lower_bound))
        if level == 0:
            return _StrictnessConfig(
                level=0,
                quality_gate_games=base_games,
                min_winrate=min_winrate,
                min_lcb=min_lcb,
                top_k_opponents=base.top_k_opponents,
                league_only=False,
                dual_seed=False,
            )
        return _StrictnessConfig(
            level=level,
            quality_gate_games=max(base_games, base.quality_gate_games),
            min_winrate=max(min_winrate, base.min_winrate),
            min_lcb=max(min_lcb, base.min_lcb),
            top_k_opponents=base.top_k_opponents,
            league_only=base.league_only,
            dual_seed=base.dual_seed,
        )

    def _compute_eval_protocol_hash(self, job: TrainingJob) -> str:
        strictness = self._strictness_config_for_job(job)
        payload = {
            "ruleset_id": job.ruleset_id,
            "lookahead_policy_version": "adaptive_v1",
            "train_split": job.params.train_split,
            "microbatch_size": job.params.microbatch_size,
            "eval_window_batches": job.params.eval_window_batches,
            "population_size": job.params.population_size,
            "worker_count": job.params.worker_count,
            "quality_gate_games": strictness.quality_gate_games,
            "quality_gate_min_winrate": strictness.min_winrate,
            "quality_gate_min_lower_bound": strictness.min_lcb,
            "top_k_opponents": strictness.top_k_opponents,
            "league_only": strictness.league_only,
            "dual_seed": strictness.dual_seed,
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]

    def _top16_signature_locked(self, ruleset_id: str) -> str:
        if self._league_service is None:
            return ""
        try:
            table = self._league_service.list_table(ruleset_id)
        except KeyError:
            return ""
        rows = [row for row in table if row.pool_type == "league"][:16]
        if not rows:
            rows = table[:16]
        payload = [
            {
                "bot_version_id": row.bot_version_id,
                "score": round(row.conservative_score, 6),
            }
            for row in rows
        ]
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]

    def _update_autoevolve_progress_locked(self, job: TrainingJob, *, improved: bool, gate_lcb: float) -> None:
        if gate_lcb > job.progress.champion_gate_lcb:
            job.progress.champion_gate_lcb = gate_lcb

        if improved:
            job.progress.meta_plateau_counter = 0
            return

        job.progress.meta_plateau_counter += 1
        if not job.params.autoevolve_enabled:
            return

        patience = max(1, int(job.params.meta_plateau_patience_cycles))
        if job.progress.meta_plateau_counter < patience:
            return

        max_level = min(int(job.params.strictness_max_level), len(self._STRICTNESS_LEVELS) - 1)
        if job.progress.strictness_level >= max_level:
            return

        old_level = job.progress.strictness_level
        job.progress.strictness_level = min(max_level, old_level + 1)
        job.progress.meta_plateau_counter = 0
        job.progress.eval_protocol_hash = self._compute_eval_protocol_hash(job)
        self._event_bus.publish_sync(
            event_type="training.strictness_changed",
            entity_id=job.id,
            ruleset_id=job.ruleset_id,
            payload={
                "old_level": old_level,
                "new_level": job.progress.strictness_level,
                "eval_protocol_hash": job.progress.eval_protocol_hash,
                "cycle_index": job.progress.cycle_index,
            },
        )

    def _apply_stage_transitions_locked(self, job: TrainingJob) -> None:
        stage = job.stage_state
        if stage is None:
            self._set_stage_locked(job, "Warmup", reason="initialized")
            return

        if stage == "Warmup" and job.progress.windows_done >= 2 and job.progress.best_score >= 0.5:
            self._set_stage_locked(job, "MainOptimization", reason="warmup_complete")
            return

        if stage == "MainOptimization" and job.progress.candidate_streak >= 2:
            self._set_stage_locked(job, "CandidateEvaluation", reason="stable_candidate")
            return

        if stage == "CandidateEvaluation" and (job.progress.windows_done - job.progress.stage_enter_window) >= 1:
            self._set_stage_locked(job, "PlateauCheck", reason="candidate_evaluated")
            return

        if stage != "PlateauCheck" and job.progress.plateau_windows >= job.params.plateau_patience_windows:
            self._set_stage_locked(job, "PlateauCheck", reason="plateau_detected")

    def _should_finish_locked(self, job: TrainingJob) -> bool:
        strong_target = max(job.params.target_score, 0.78)
        if job.progress.last_score >= strong_target and job.progress.plateau_windows >= 3:
            job.stop_reason = "strong_found_plateau"
            return True

        weak_window = max(4, job.params.plateau_patience_windows)
        if (
            job.progress.windows_done >= weak_window
            and job.progress.best_score < 0.52
            and job.progress.plateau_windows >= job.params.plateau_patience_windows
        ):
            job.stop_reason = "weak_plateau"
            return True

        if (
            job.progress.windows_done >= job.params.min_windows_before_early_stop
            and job.progress.plateau_windows >= job.params.early_stop_plateau_windows
        ):
            job.stop_reason = "plateau_early_stop"
            return True

        if job.progress.last_score >= job.params.target_score and job.progress.plateau_windows >= 3:
            job.stop_reason = "target_reached_plateau"
            return True

        return False

    def _get_checkpoint_locked(self, job_id: str, checkpoint_id: str) -> TrainingCheckpoint:
        for checkpoint in self._checkpoints.get(job_id, []):
            if checkpoint.checkpoint_id == checkpoint_id:
                return checkpoint
        raise KeyError(f"Unknown checkpoint_id={checkpoint_id} for job_id={job_id}")

    def _ensure_state(self, job: TrainingJob, allowed: set[str], command: str) -> None:
        if job.lifecycle_state not in allowed:
            raise ValueError(
                f"Invalid command '{command}' for state '{job.lifecycle_state}'. Allowed: {sorted(allowed)}"
            )

    def _set_state_locked(self, job: TrainingJob, new_state: LifecycleState, publish_async: bool = True) -> None:
        old_state = job.lifecycle_state
        job.lifecycle_state = new_state
        self._persist_job_locked(job)
        if publish_async:
            self._event_bus.publish_sync(
                event_type="job.lifecycle_changed",
                entity_id=job.id,
                ruleset_id=job.ruleset_id,
                payload={"old_state": old_state, "new_state": new_state},
            )

    def _set_stage_locked(self, job: TrainingJob, new_stage: StageState, reason: str, publish_async: bool = True) -> None:
        old_stage = job.stage_state
        job.stage_state = new_stage
        job.progress.stage_enter_window = job.progress.windows_done
        self._persist_job_locked(job)
        if publish_async:
            self._event_bus.publish_sync(
                event_type="training.stage_changed",
                entity_id=job.id,
                ruleset_id=job.ruleset_id,
                payload={"old_stage": old_stage, "stage_state": new_stage, "reason": reason},
            )
