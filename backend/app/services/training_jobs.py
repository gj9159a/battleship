import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from app.rulesets import get_ruleset
from app.services.events import EventBus
from app.trainer import CheckpointStore, DeterministicSimulator, TrainingCheckpoint, TrainingParams, TrainingProgress
from app.trainer.models import LifecycleState, StageState


@dataclass(slots=True)
class TrainingJob:
    id: str
    ruleset_id: str
    lifecycle_state: LifecycleState
    stage_state: StageState | None
    profile_id: str | None
    seed: int
    params: TrainingParams
    progress: TrainingProgress
    stop_reason: str | None = None


@dataclass(slots=True)
class _TrainingRuntime:
    thread: threading.Thread | None = None
    run_gate: threading.Event = field(default_factory=threading.Event)
    pause_requested: bool = False
    stop_requested: bool = False
    simulator: DeterministicSimulator | None = None


class TrainingJobService:
    def __init__(self, event_bus: EventBus, checkpoint_root: Path | None = None) -> None:
        self._jobs: dict[str, TrainingJob] = {}
        self._event_bus = event_bus
        self._checkpoints: dict[str, list[TrainingCheckpoint]] = {}
        self._runtimes: dict[str, _TrainingRuntime] = {}
        self._lock = threading.RLock()
        root = checkpoint_root or (Path.cwd() / ".data" / "training_checkpoints")
        self._checkpoint_store = CheckpointStore(root)

    def create_job(
        self,
        ruleset_id: str,
        profile_id: str | None,
        seed: int | None,
        params: TrainingParams | None = None,
    ) -> TrainingJob:
        get_ruleset(ruleset_id)
        resolved_params = params or TrainingParams()
        resolved_seed = seed if seed is not None else 0
        job = TrainingJob(
            id=str(uuid4()),
            ruleset_id=ruleset_id,
            lifecycle_state="Idle",
            stage_state=None,
            profile_id=profile_id,
            seed=resolved_seed,
            params=resolved_params,
            progress=TrainingProgress(),
        )
        with self._lock:
            self._jobs[job.id] = job
            self._checkpoints[job.id] = []
            self._runtimes[job.id] = _TrainingRuntime(simulator=DeterministicSimulator(resolved_seed))
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
                return

            runtime.run_gate.wait()

            with self._lock:
                job = self._jobs[job_id]
                runtime = self._runtimes[job_id]

                if runtime.stop_requested and job.lifecycle_state == "Stopping":
                    self._set_stage_locked(job, "Finished", reason=job.stop_reason or "stopped")
                    self._set_state_locked(job, "Stopped")
                    runtime.run_gate.clear()
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
                    return

                if job.lifecycle_state == "Pausing":
                    runtime.run_gate.clear()
                    self._set_state_locked(job, "Paused")
                    continue

                if job.lifecycle_state != "Running":
                    continue

                self._run_microbatch_locked(job)

                if runtime.stop_requested:
                    self._set_stage_locked(job, "Finished", reason=job.stop_reason or "stopped")
                    self._set_state_locked(job, "Stopped")
                    runtime.run_gate.clear()
                    return

                if runtime.pause_requested:
                    runtime.run_gate.clear()
                    self._set_state_locked(job, "Paused")
                    continue

                if self._should_finish_locked(job):
                    self._set_stage_locked(job, "Finished", reason=job.stop_reason or "completed")
                    self._set_state_locked(job, "Completed")
                    runtime.run_gate.clear()
                    return

            time.sleep(0.0005)

    def _run_microbatch_locked(self, job: TrainingJob) -> None:
        job.progress.batches_done += 1
        job.progress.games_played += job.params.microbatch_size

        if job.progress.batches_done % job.params.eval_window_batches == 0:
            runtime = self._runtimes[job.id]
            if runtime.simulator is None:
                runtime.simulator = DeterministicSimulator(job.seed)

            metrics = runtime.simulator.next_window(job.progress.windows_done)
            prev_best = job.progress.best_score
            job.progress.windows_done += 1
            job.progress.last_score = metrics.score

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

            self._event_bus.publish_sync(
                event_type="training.metrics",
                entity_id=job.id,
                ruleset_id=job.ruleset_id,
                payload={
                    "windows_done": job.progress.windows_done,
                    "wr_baseline": metrics.wr_baseline,
                    "wr_active": metrics.wr_active,
                    "avg_turns_win": metrics.avg_turns_win,
                    "score": metrics.score,
                    "best_score": job.progress.best_score,
                    "plateau_windows": job.progress.plateau_windows,
                },
            )

            self._apply_stage_transitions_locked(job)

        if job.progress.batches_done % job.params.checkpoint_interval_batches == 0:
            checkpoint = self._checkpoint_store.save(
                job_id=job.id,
                batches_done=job.progress.batches_done,
                games_played=job.progress.games_played,
                best_score=job.progress.best_score,
                stage_state=job.stage_state,
            )
            self._checkpoints[job.id].append(checkpoint)
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
        if job.progress.games_played >= job.params.budget_games:
            job.stop_reason = "budget_exhausted"
            return True

        if job.progress.plateau_windows >= job.params.early_stop_plateau_windows:
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
        if publish_async:
            self._event_bus.publish_sync(
                event_type="training.stage_changed",
                entity_id=job.id,
                ruleset_id=job.ruleset_id,
                payload={"old_stage": old_stage, "stage_state": new_stage, "reason": reason},
            )
