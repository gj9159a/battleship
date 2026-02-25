import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.training_jobs import TrainingJobService, _PromotionAttemptResult


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("BATTLESHIP_DATA_DIR", str(tmp_path / ".data"))
    monkeypatch.setattr(
        TrainingJobService,
        "_maybe_auto_promote_weights_locked",
        lambda *args, **kwargs: _PromotionAttemptResult(attempted=False, passed=False, rank=-1),
    )
    return TestClient(create_app(enable_frozen_benchmarks=False))
