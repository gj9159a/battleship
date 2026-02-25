import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.training_jobs import TrainingJobService


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("BATTLESHIP_DATA_DIR", str(tmp_path / ".data"))
    monkeypatch.setattr(TrainingJobService, "_maybe_auto_promote_weights_locked", lambda *args, **kwargs: None)
    return TestClient(create_app(enable_frozen_benchmarks=True))


def test_benchmarks_suites_and_runs_endpoints(client: TestClient) -> None:
    initial_suites = client.get("/api/v1/benchmarks/suites?ruleset_id=classic_v1&suite_tier=canonical")
    assert initial_suites.status_code == 200
    initial_payload = initial_suites.json()
    assert {item["suite_kind"] for item in initial_payload} == {"random", "strong"}
    assert all(item["suite_tier"] == "canonical" for item in initial_payload)

    ensured_ci = client.post(
        "/api/v1/benchmarks/suites/ensure",
        json={"ruleset_id": "classic_v1", "suite_tier": "ci_smoke"},
    )
    assert ensured_ci.status_code == 200
    assert {item["suite_tier"] for item in ensured_ci.json()} == {"ci_smoke"}

    suites_response = client.get("/api/v1/benchmarks/suites?ruleset_id=classic_v1&suite_tier=canonical")
    assert suites_response.status_code == 200
    suites = suites_response.json()
    kinds = {item["suite_kind"] for item in suites}
    assert kinds == {"random", "strong"}
    assert all(item["suite_tier"] == "canonical" for item in suites)

    random_suite = next(item for item in suites if item["suite_kind"] == "random")
    run_response = client.post(
        f"/api/v1/benchmarks/suites/{random_suite['suite_id']}/runs/bot-version",
        json={"bot_version_id": "classic_v1-baseline-strong"},
    )
    assert run_response.status_code == 200
    run_payload = run_response.json()
    assert run_payload["suite_id"] == random_suite["suite_id"]
    assert run_payload["subject_type"] == "bot_version"
    assert run_payload["subject_ref"] == "classic_v1-baseline-strong"
    assert "suite_protocol_hash" in run_payload

    listed_runs = client.get(f"/api/v1/benchmarks/suites/{random_suite['suite_id']}/runs")
    assert listed_runs.status_code == 200
    assert listed_runs.json()

    checkpoint_run = client.post(
        f"/api/v1/benchmarks/suites/{random_suite['suite_id']}/runs/checkpoint",
        json={"job_id": "disabled", "checkpoint_id": "disabled"},
    )
    assert checkpoint_run.status_code == 410


def test_benchmarks_bias_analysis_endpoints(client: TestClient) -> None:
    analyzed = client.post(
        "/api/v1/benchmarks/placement-bias/analyze",
        json={"ruleset_id": "classic_v1", "sample_count": 32, "seed_anchor": 123},
    )
    assert analyzed.status_code == 200
    report = analyzed.json()
    assert report["ruleset_id"] == "classic_v1"
    assert report["sample_count"] == 32
    assert report["seed_anchor"] == 123
    assert report["seed_reproducibility_check"]["deterministic"] is True

    latest = client.get("/api/v1/benchmarks/placement-bias/latest?ruleset_id=classic_v1")
    assert latest.status_code == 200
    latest_report = latest.json()
    assert latest_report["report_id"] == report["report_id"]
