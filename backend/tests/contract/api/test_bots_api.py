import time

from fastapi.testclient import TestClient


def _wait_for_checkpoint(client: TestClient, job_id: str, timeout: float = 6.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f'/api/v1/training/jobs/{job_id}/checkpoints')
        assert response.status_code == 200
        payload = response.json()
        if payload:
            return payload[0]
        time.sleep(0.02)
    raise AssertionError(f'job {job_id} did not produce checkpoints')


def _create_training_job(client: TestClient, ruleset_id: str) -> str:
    created = client.post(
        '/api/v1/training/jobs',
        json={
            'ruleset_id': ruleset_id,
            'seed': 10,
            'params': {
                'microbatch_size': 5,
                'eval_window_batches': 1,
                'checkpoint_interval_batches': 1,
                'population_size': 2,
                'train_split': 0.6,
                'worker_count': 1,
                'quality_gate_games': 20,
                'target_score': 1.0,
                'early_stop_plateau_windows': 1000,
                'tick_delay_ms': 0,
            },
        },
    )
    assert created.status_code == 200
    job_id = created.json()['id']

    started = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'start'})
    assert started.status_code == 200
    return job_id


def test_bots_from_checkpoint_and_labels(client: TestClient) -> None:
    job_id = _create_training_job(client, 'classic_v1')
    checkpoint = _wait_for_checkpoint(client, job_id)

    created = client.post(
        '/api/v1/bots/from-checkpoint',
        json={
            'job_id': job_id,
            'checkpoint_id': checkpoint['checkpoint_id'],
            'bot_version_id': 'candidate-001',
            'policy_type': 'probability_strong',
            'feature_schema_version': 'classic_features_v1',
            'lookahead_policy_version': 'adaptive_v1',
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload['bot_version_id'] == 'candidate-001'
    assert payload['ruleset_id'] == 'classic_v1'
    assert payload['source_checkpoint_id'] == checkpoint['checkpoint_id']
    assert isinstance(payload['weights'], dict)
    assert 'hunt_heat' in payload['weights']

    listed = client.get('/api/v1/bots?ruleset_id=classic_v1')
    assert listed.status_code == 200
    assert any(item['bot_version_id'] == 'candidate-001' for item in listed.json())

    labels = client.patch(
        '/api/v1/bots/candidate-001/labels',
        json={'is_baseline': True, 'is_legacy': True},
    )
    assert labels.status_code == 200
    assert sorted(labels.json()['tags']) == ['baseline', 'legacy']

    without_legacy = client.get('/api/v1/bots?include_legacy=false')
    assert without_legacy.status_code == 200
    assert all(item['bot_version_id'] != 'candidate-001' for item in without_legacy.json())


def test_bots_checkpoints_endpoint_filters_by_ruleset(client: TestClient) -> None:
    ruleset_created = client.post(
        '/api/v1/rulesets',
        json={
            'id': 'classic_alt_v1',
            'name': 'Classic Alt v1',
            'board_size': 10,
            'fleet': [5, 4, 3, 3, 2],
            'placement_no_touch': False,
            'extra_turn_on_hit': True,
        },
    )
    assert ruleset_created.status_code == 200

    job_a = _create_training_job(client, 'classic_v1')
    _wait_for_checkpoint(client, job_a)
    client.post(f"/api/v1/training/jobs/{job_a}/commands", json={"command": "stop"})

    job_b = _create_training_job(client, 'classic_alt_v1')
    _wait_for_checkpoint(client, job_b)
    client.post(f"/api/v1/training/jobs/{job_b}/commands", json={"command": "stop"})

    classic_only = client.get('/api/v1/bots/checkpoints?ruleset_id=classic_v1')
    assert classic_only.status_code == 200
    assert classic_only.json()
    assert all(item['ruleset_id'] == 'classic_v1' for item in classic_only.json())

    all_rows = client.get('/api/v1/bots/checkpoints')
    assert all_rows.status_code == 200
    ruleset_ids = {item['ruleset_id'] for item in all_rows.json()}
    assert {'classic_v1', 'classic_alt_v1'}.issubset(ruleset_ids)
