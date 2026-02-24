from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from app.rulesets import get_ruleset
from app.services.events import EventBus

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


@dataclass(slots=True)
class TrainingJob:
    id: str
    ruleset_id: str
    lifecycle_state: LifecycleState
    stage_state: str | None
    profile_id: str | None
    seed: int | None
    stop_reason: str | None = None


class TrainingJobService:
    def __init__(self, event_bus: EventBus) -> None:
        self._jobs: dict[str, TrainingJob] = {}
        self._event_bus = event_bus

    def create_job(self, ruleset_id: str, profile_id: str | None, seed: int | None) -> TrainingJob:
        get_ruleset(ruleset_id)
        job = TrainingJob(
            id=str(uuid4()),
            ruleset_id=ruleset_id,
            lifecycle_state="Idle",
            stage_state=None,
            profile_id=profile_id,
            seed=seed,
        )
        self._jobs[job.id] = job
        return job

    def get_job(self, job_id: str) -> TrainingJob:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise KeyError(f"Unknown training job id={job_id}") from exc

    async def apply_command(self, job_id: str, command: str) -> TrainingJob:
        job = self.get_job(job_id)

        if command == "start":
            self._ensure_state(job, {"Idle"}, command)
            await self._set_state(job, "Running")
            job.stage_state = "Warmup"
            await self._event_bus.publish(
                event_type="training.stage_changed",
                entity_id=job.id,
                ruleset_id=job.ruleset_id,
                payload={"stage_state": job.stage_state, "reason": "job_started"},
            )
            return job

        if command == "pause":
            self._ensure_state(job, {"Running"}, command)
            await self._set_state(job, "Pausing")
            await self._set_state(job, "Paused")
            return job

        if command == "resume":
            self._ensure_state(job, {"Paused"}, command)
            await self._set_state(job, "Running")
            return job

        if command == "stop":
            self._ensure_state(job, {"Running", "Pausing", "Paused"}, command)
            await self._set_state(job, "Stopping")
            job.stop_reason = "stopped_by_user"
            await self._set_state(job, "Stopped")
            return job

        raise ValueError(f"Unknown command: {command}")

    def _ensure_state(self, job: TrainingJob, allowed: set[str], command: str) -> None:
        if job.lifecycle_state not in allowed:
            raise ValueError(
                f"Invalid command '{command}' for state '{job.lifecycle_state}'. Allowed: {sorted(allowed)}"
            )

    async def _set_state(self, job: TrainingJob, new_state: LifecycleState) -> None:
        old_state = job.lifecycle_state
        job.lifecycle_state = new_state
        await self._event_bus.publish(
            event_type="job.lifecycle_changed",
            entity_id=job.id,
            ruleset_id=job.ruleset_id,
            payload={"old_state": old_state, "new_state": new_state},
        )
