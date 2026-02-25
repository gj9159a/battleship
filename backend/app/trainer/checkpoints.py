import json
from pathlib import Path

from app.trainer.models import TrainingCheckpoint


class CheckpointStore:
    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir
        self._root_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        *,
        job_id: str,
        batches_done: int,
        games_played: int,
        best_score: float,
        stage_state: str | None,
        current_weights: dict[str, float] | None = None,
        best_weights: dict[str, float] | None = None,
        search_state: dict[str, object] | None = None,
    ) -> TrainingCheckpoint:
        checkpoint_id = f"{job_id}-b{batches_done}"
        job_dir = self._root_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        path = job_dir / f"{checkpoint_id}.json"

        payload = {
            "checkpoint_id": checkpoint_id,
            "job_id": job_id,
            "batches_done": batches_done,
            "games_played": games_played,
            "best_score": best_score,
            "stage_state": stage_state,
            "current_weights": current_weights or {},
            "best_weights": best_weights or {},
            "search_state": search_state or {},
        }
        path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")

        return TrainingCheckpoint(
            checkpoint_id=checkpoint_id,
            job_id=job_id,
            path=str(path),
            batches_done=batches_done,
            games_played=games_played,
            best_score=best_score,
            stage_state=stage_state,
        )

    def load(self, checkpoint: TrainingCheckpoint) -> dict:
        path = Path(checkpoint.path)
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint file not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))
