from fastapi.testclient import TestClient


def test_training_job_lifecycle_rest(client: TestClient) -> None:

    created = client.post('/api/v1/training/jobs', json={'ruleset_id': 'classic_v1', 'seed': 42})
    assert created.status_code == 200
    job_id = created.json()['id']
    assert created.json()['lifecycle_state'] == 'Idle'

    pause_invalid = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'pause'})
    assert pause_invalid.status_code == 409

    started = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'start'})
    assert started.status_code == 200
    assert started.json()['lifecycle_state'] == 'Running'
    assert started.json()['stage_state'] == 'Warmup'

    paused = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'pause'})
    assert paused.status_code == 200
    assert paused.json()['lifecycle_state'] == 'Paused'

    resumed = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'resume'})
    assert resumed.status_code == 200
    assert resumed.json()['lifecycle_state'] == 'Running'

    stopped = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'stop'})
    assert stopped.status_code == 200
    assert stopped.json()['lifecycle_state'] == 'Stopped'
    assert stopped.json()['stop_reason'] == 'stopped_by_user'


def test_training_ws_emits_lifecycle_and_stage_events(client: TestClient) -> None:
    created = client.post('/api/v1/training/jobs', json={'ruleset_id': 'classic_v1'})
    job_id = created.json()['id']

    with client.websocket_connect('/api/v1/ws') as ws:
        response = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'start'})
        assert response.status_code == 200

        event1 = ws.receive_json()
        event2 = ws.receive_json()

    assert event1['entity_id'] == job_id
    assert event1['event_type'] == 'job.lifecycle_changed'
    assert event2['entity_id'] == job_id
    assert event2['event_type'] == 'training.stage_changed'
