import time

from fastapi.testclient import TestClient


def _wait_for_checkpoint(client: TestClient, job_id: str, timeout: float = 6.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/v1/training/jobs/{job_id}/checkpoints")
        assert response.status_code == 200
        payload = response.json()
        if payload:
            return payload[0]
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not produce checkpoints")


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

    created = client.post(
        "/api/v1/training/jobs",
        json={
            "ruleset_id": "classic_v1",
            "seed": 42,
            "params": {
                "microbatch_size": 5,
                "eval_window_batches": 1,
                "checkpoint_interval_batches": 1,
                "population_size": 4,
                "train_split": 0.6,
                "worker_count": 1,
                "quality_gate_games": 20,
                "target_score": 1.0,
                "early_stop_plateau_windows": 1000,
                "tick_delay_ms": 1,
            },
        },
    )
    assert created.status_code == 200
    job_id = created.json()["id"]

    started = client.post(f"/api/v1/training/jobs/{job_id}/commands", json={"command": "start"})
    assert started.status_code == 200

    checkpoint = _wait_for_checkpoint(client, job_id)
    suites_response = client.get("/api/v1/benchmarks/suites?ruleset_id=classic_v1&suite_tier=canonical")
    assert suites_response.status_code == 200
    suites = suites_response.json()
    kinds = {item["suite_kind"] for item in suites}
    assert kinds == {"random", "strong"}
    assert all(item["suite_tier"] == "canonical" for item in suites)

    checkpoint_bot = client.post(
        "/api/v1/bots/from-checkpoint",
        json={
            "job_id": job_id,
            "checkpoint_id": checkpoint["checkpoint_id"],
            "bot_version_id": "bench-candidate-001",
        },
    )
    assert checkpoint_bot.status_code == 200

    random_suite = next(item for item in suites if item["suite_kind"] == "random")
    run_response = client.post(
        f"/api/v1/benchmarks/suites/{random_suite['suite_id']}/runs/bot-version",
        json={"bot_version_id": "bench-candidate-001"},
    )
    assert run_response.status_code == 200
    run_payload = run_response.json()
    assert run_payload["suite_id"] == random_suite["suite_id"]
    assert run_payload["subject_type"] == "bot_version"
    assert run_payload["subject_ref"] == "bench-candidate-001"
    assert "suite_protocol_hash" in run_payload

    listed_runs = client.get(f"/api/v1/benchmarks/suites/{random_suite['suite_id']}/runs")
    assert listed_runs.status_code == 200
    assert listed_runs.json()

    checkpoint_run = client.post(
        f"/api/v1/benchmarks/suites/{random_suite['suite_id']}/runs/checkpoint",
        json={"job_id": job_id, "checkpoint_id": checkpoint["checkpoint_id"]},
    )
    assert checkpoint_run.status_code == 200
    assert checkpoint_run.json()["subject_type"] == "checkpoint"


def test_benchmarks_bias_analysis_endpoints(client: TestClient) -> None:
    analyzed = client.post(
        "/api/v1/benchmarks/placement-bias/analyze",
        json={"ruleset_id": "classic_v1", "sample_count": 128, "seed_anchor": 123},
    )
    assert analyzed.status_code == 200
    report = analyzed.json()
    assert report["ruleset_id"] == "classic_v1"
    assert report["sample_count"] == 128
    assert report["seed_anchor"] == 123
    assert report["seed_reproducibility_check"]["deterministic"] is True

    latest = client.get("/api/v1/benchmarks/placement-bias/latest?ruleset_id=classic_v1")
    assert latest.status_code == 200
    latest_report = latest.json()
    assert latest_report["report_id"] == report["report_id"]
