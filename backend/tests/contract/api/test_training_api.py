import time

from fastapi.testclient import TestClient


def _fast_params(**overrides: float | int) -> dict[str, float | int]:
    params: dict[str, float | int] = {
        'microbatch_size': 10,
        'eval_window_batches': 1,
        'checkpoint_interval_batches': 1,
        'population_size': 4,
        'train_split': 0.6,
        'worker_count': 1,
        'quality_gate_games': 20,
        'target_score': 1.0,
        'early_stop_plateau_windows': 1000,
        'min_windows_before_early_stop': 1,
        'tick_delay_ms': 10,
    }
    params.update(overrides)
    return params


def _wait_for_state(client: TestClient, job_id: str, target_state: str, timeout: float = 6.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f'/api/v1/training/jobs/{job_id}')
        assert response.status_code == 200
        payload = response.json()
        if payload['lifecycle_state'] == target_state:
            return payload
        time.sleep(0.02)
    raise AssertionError(f'job {job_id} did not reach state={target_state}')


def test_training_job_lifecycle_rest(client: TestClient) -> None:
    created = client.post(
        '/api/v1/training/jobs',
        json={
            'ruleset_id': 'classic_v1',
            'seed': 42,
            'params': _fast_params(tick_delay_ms=20),
        },
    )
    assert created.status_code == 200
    job_id = created.json()['id']
    assert created.json()['lifecycle_state'] == 'Idle'

    pause_invalid = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'pause'})
    assert pause_invalid.status_code == 409

    started = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'start'})
    assert started.status_code == 200
    assert started.json()['lifecycle_state'] == 'Running'
    assert started.json()['stage_state'] == 'Warmup'

    pausing = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'pause'})
    assert pausing.status_code == 200
    assert pausing.json()['lifecycle_state'] == 'Pausing'

    paused = _wait_for_state(client, job_id, 'Paused')
    assert paused['progress']['games_played'] >= 0
    assert paused['progress']['games_played'] % 10 == 0

    resumed = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'resume'})
    assert resumed.status_code == 200
    assert resumed.json()['lifecycle_state'] == 'Running'

    stopping = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'stop'})
    assert stopping.status_code == 200
    assert stopping.json()['lifecycle_state'] in ('Stopping', 'Stopped')

    stopped = _wait_for_state(client, job_id, 'Stopped')
    assert stopped['stop_reason'] == 'stopped_by_user'


def test_training_checkpoints_save_and_load(client: TestClient) -> None:
    created = client.post(
        '/api/v1/training/jobs',
        json={
            'ruleset_id': 'classic_v1',
            'params': _fast_params(microbatch_size=5),
        },
    )
    job_id = created.json()['id']

    started = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'start'})
    assert started.status_code == 200

    checkpoints_payload = []
    deadline = time.time() + 6.0
    while time.time() < deadline:
        checkpoints = client.get(f'/api/v1/training/jobs/{job_id}/checkpoints')
        assert checkpoints.status_code == 200
        checkpoints_payload = checkpoints.json()
        if checkpoints_payload:
            break
        time.sleep(0.02)
    assert checkpoints_payload

    client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'pause'})
    _wait_for_state(client, job_id, 'Paused')

    checkpoint = checkpoints_payload[0]
    loaded = client.post(f"/api/v1/training/jobs/{job_id}/resume-from/{checkpoint['checkpoint_id']}")
    assert loaded.status_code == 200
    assert loaded.json()['progress']['batches_done'] == checkpoint['batches_done']
    assert loaded.json()['progress']['games_played'] == checkpoint['games_played']


def test_training_adaptive_completion(client: TestClient) -> None:
    created = client.post(
        '/api/v1/training/jobs',
        json={
            'ruleset_id': 'classic_v1',
            'seed': 7,
            'params': _fast_params(
                checkpoint_interval_batches=5,
                improvement_delta=1.0,
                plateau_delta=1.0,
                early_stop_plateau_windows=2,
                min_windows_before_early_stop=1,
                tick_delay_ms=0,
            ),
        },
    )
    job_id = created.json()['id']

    started = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'start'})
    assert started.status_code == 200

    completed = _wait_for_state(client, job_id, 'Completed', timeout=20.0)
    assert completed['stage_state'] == 'Finished'
    assert completed['stop_reason'] in (
        'strong_found_plateau',
        'weak_plateau',
        'plateau_early_stop',
        'target_reached_plateau',
    )


def test_training_early_stop_respects_min_windows_threshold(client: TestClient) -> None:
    created = client.post(
        '/api/v1/training/jobs',
        json={
            'ruleset_id': 'classic_v1',
            'seed': 77,
            'params': _fast_params(
                target_score=1.0,
                improvement_delta=1.0,
                plateau_delta=1.0,
                plateau_patience_windows=1000,
                early_stop_plateau_windows=1,
                min_windows_before_early_stop=4,
                checkpoint_interval_batches=1000,
                tick_delay_ms=0,
            ),
        },
    )
    assert created.status_code == 200
    job_id = created.json()['id']

    started = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'start'})
    assert started.status_code == 200

    completed = _wait_for_state(client, job_id, 'Completed', timeout=20.0)
    assert completed['stop_reason'] == 'plateau_early_stop'
    assert completed['progress']['windows_done'] >= 4


def test_training_ws_emits_lifecycle_stage_and_metrics_events(client: TestClient) -> None:
    created = client.post(
        '/api/v1/training/jobs',
        json={
            'ruleset_id': 'classic_v1',
            'seed': 123,
            'params': _fast_params(),
        },
    )
    job_id = created.json()['id']

    seen_types: set[str] = set()
    with client.websocket_connect('/api/v1/ws') as ws:
        response = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'start'})
        assert response.status_code == 200

        for _ in range(8):
            event = ws.receive_json()
            if event['entity_id'] == job_id:
                seen_types.add(event['event_type'])
            if {'job.lifecycle_changed', 'training.stage_changed', 'training.metrics'}.issubset(seen_types):
                break

    assert 'job.lifecycle_changed' in seen_types
    assert 'training.stage_changed' in seen_types
    assert 'training.metrics' in seen_types


def test_training_job_accepts_seed_bot_version(client: TestClient) -> None:
    source_job = client.post(
        '/api/v1/training/jobs',
        json={
            'ruleset_id': 'classic_v1',
            'seed': 22,
            'params': _fast_params(microbatch_size=5, tick_delay_ms=5),
        },
    )
    assert source_job.status_code == 200
    source_job_id = source_job.json()['id']
    started = client.post(f'/api/v1/training/jobs/{source_job_id}/commands', json={'command': 'start'})
    assert started.status_code == 200

    checkpoint_id = None
    deadline = time.time() + 2.0
    while time.time() < deadline:
        checkpoints = client.get(f'/api/v1/training/jobs/{source_job_id}/checkpoints')
        assert checkpoints.status_code == 200
        payload = checkpoints.json()
        if payload:
            checkpoint_id = payload[0]['checkpoint_id']
            break
        time.sleep(0.02)
    assert checkpoint_id is not None

    bot_created = client.post(
        '/api/v1/bots/from-checkpoint',
        json={
            'job_id': source_job_id,
            'checkpoint_id': checkpoint_id,
            'bot_version_id': 'candidate-001',
        },
    )
    assert bot_created.status_code == 200

    created = client.post(
        '/api/v1/training/jobs',
        json={
            'ruleset_id': 'classic_v1',
            'seed_bot_version_id': 'candidate-001',
            'seed': 101,
        },
    )

    assert created.status_code == 200
    assert created.json()['seed_bot_version_id'] == 'candidate-001'


def test_training_job_rejects_unknown_seed_bot(client: TestClient) -> None:
    created = client.post(
        '/api/v1/training/jobs',
        json={
            'ruleset_id': 'classic_v1',
            'seed_bot_version_id': 'unknown-bot',
            'seed': 101,
        },
    )

    assert created.status_code == 404


def test_training_job_rejects_seed_bot_with_foreign_ruleset(client: TestClient) -> None:
    ruleset_created = client.post(
        '/api/v1/rulesets',
        json={
            'id': 'classic_alt_v2',
            'name': 'Classic Alt v2',
            'board_size': 10,
            'fleet': [5, 4, 3, 3, 2],
            'placement_no_touch': False,
            'extra_turn_on_hit': True,
        },
    )
    assert ruleset_created.status_code == 200

    source_job = client.post(
        '/api/v1/training/jobs',
        json={
            'ruleset_id': 'classic_v1',
            'seed': 33,
            'params': _fast_params(microbatch_size=5, tick_delay_ms=5),
        },
    )
    assert source_job.status_code == 200
    source_job_id = source_job.json()['id']
    started = client.post(f'/api/v1/training/jobs/{source_job_id}/commands', json={'command': 'start'})
    assert started.status_code == 200

    checkpoint_id = None
    deadline = time.time() + 2.0
    while time.time() < deadline:
        checkpoints = client.get(f'/api/v1/training/jobs/{source_job_id}/checkpoints')
        assert checkpoints.status_code == 200
        payload = checkpoints.json()
        if payload:
            checkpoint_id = payload[0]['checkpoint_id']
            break
        time.sleep(0.02)
    assert checkpoint_id is not None

    bot_created = client.post(
        '/api/v1/bots/from-checkpoint',
        json={
            'job_id': source_job_id,
            'checkpoint_id': checkpoint_id,
            'bot_version_id': 'classic-v1-seed-1',
        },
    )
    assert bot_created.status_code == 200

    invalid = client.post(
        '/api/v1/training/jobs',
        json={
            'ruleset_id': 'classic_alt_v2',
            'seed_bot_version_id': 'classic-v1-seed-1',
            'seed': 10,
        },
    )
    assert invalid.status_code == 422
