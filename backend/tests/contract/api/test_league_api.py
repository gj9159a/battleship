import time

from fastapi.testclient import TestClient


def _wait_season_state(client: TestClient, season_id: str, target: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/v1/league/seasons/{season_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["lifecycle_state"] == target:
            return payload
        time.sleep(0.02)
    raise AssertionError(f"season {season_id} did not reach state={target}")


def test_league_register_match_and_table(client: TestClient) -> None:
    a = client.post("/api/v1/league/classic_v1/bots", json={"bot_version_id": "bot-a", "pool_type": "active"})
    b = client.post("/api/v1/league/classic_v1/bots", json={"bot_version_id": "bot-b", "pool_type": "active"})
    assert a.status_code == 200
    assert b.status_code == 200

    match = client.post(
        "/api/v1/league/classic_v1/matches",
        json={"bot_a_id": "bot-a", "bot_b_id": "bot-b", "winner_id": "bot-a"},
    )
    assert match.status_code == 200

    table = client.get("/api/v1/league/classic_v1/table")
    assert table.status_code == 200
    rows = table.json()
    assert rows[0]["bot_version_id"] == "bot-a"
    assert rows[0]["conservative_score"] >= rows[1]["conservative_score"]
    assert rows[0]["matches_played"] == 1
    assert rows[1]["matches_played"] == 1

    matrix = client.get("/api/v1/league/classic_v1/matchup-matrix")
    assert matrix.status_code == 200
    assert matrix.json()[0]["total"] == 1


def test_league_top16_active_baseline_logic(client: TestClient) -> None:
    for idx in range(2):
        response = client.post(
            "/api/v1/league/classic_v1/bots",
            json={"bot_version_id": f"base-{idx}", "pool_type": "baseline"},
        )
        assert response.status_code == 200

    for idx in range(20):
        response = client.post(
            "/api/v1/league/classic_v1/bots",
            json={"bot_version_id": f"cand-{idx:02d}", "pool_type": "active"},
        )
        assert response.status_code == 200

    table = client.get("/api/v1/league/classic_v1/table")
    rows = table.json()

    pools: dict[str, int] = {}
    for row in rows:
        pools[row["pool_type"]] = pools.get(row["pool_type"], 0) + 1

    assert pools.get("baseline", 0) == 2
    assert pools.get("league", 0) == 16
    assert pools.get("active", 0) == 4


def test_league_season_job_lifecycle(client: TestClient) -> None:
    for bot_id in ("season-a", "season-b", "season-c"):
        response = client.post(
            "/api/v1/league/classic_v1/bots",
            json={"bot_version_id": bot_id, "pool_type": "active"},
        )
        assert response.status_code == 200

    created = client.post(
        "/api/v1/league/seasons",
        json={
            "ruleset_id": "classic_v1",
            "seed": 3,
            "max_matches": 10000,
            "microbatch_size": 5,
        },
    )
    assert created.status_code == 200
    season_id = created.json()["id"]

    started = client.post(f"/api/v1/league/jobs/{season_id}/commands", json={"command": "start"})
    assert started.status_code == 200
    assert started.json()["lifecycle_state"] == "Running"

    pausing = client.post(f"/api/v1/league/jobs/{season_id}/commands", json={"command": "pause"})
    assert pausing.status_code == 200
    assert pausing.json()["lifecycle_state"] in ("Pausing", "Paused")

    paused = _wait_season_state(client, season_id, "Paused")
    assert paused["matches_done"] % paused["microbatch_size"] == 0

    resumed = client.post(f"/api/v1/league/jobs/{season_id}/commands", json={"command": "resume"})
    assert resumed.status_code == 200
    assert resumed.json()["lifecycle_state"] == "Running"

    stopping = client.post(f"/api/v1/league/jobs/{season_id}/commands", json={"command": "stop"})
    assert stopping.status_code == 200
    assert stopping.json()["lifecycle_state"] in ("Stopping", "Stopped")

    stopped = _wait_season_state(client, season_id, "Stopped")
    assert stopped["stop_reason"] == "stopped_by_user"


def test_league_ws_emits_lifecycle_and_rating_events(client: TestClient) -> None:
    client.post("/api/v1/league/classic_v1/bots", json={"bot_version_id": "ws-a", "pool_type": "active"})
    client.post("/api/v1/league/classic_v1/bots", json={"bot_version_id": "ws-b", "pool_type": "active"})

    with client.websocket_connect("/api/v1/ws") as ws:
        match = client.post(
            "/api/v1/league/classic_v1/matches",
            json={"bot_a_id": "ws-a", "bot_b_id": "ws-b", "winner_id": "ws-a"},
        )
        assert match.status_code == 200

        seen: set[str] = set()
        for _ in range(6):
            event = ws.receive_json()
            if event["ruleset_id"] == "classic_v1":
                seen.add(event["event_type"])
            if {"league.match_finished", "league.rating_updated"}.issubset(seen):
                break

    assert "league.match_finished" in seen
    assert "league.rating_updated" in seen
