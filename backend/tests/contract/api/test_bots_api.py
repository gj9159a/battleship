from fastapi.testclient import TestClient


def _bootstrap_baselines(client: TestClient) -> None:
    created = client.post(
        '/api/v1/training/jobs',
        json={
            'ruleset_id': 'classic_v1',
            'seed': 10,
            'params': {
                'microbatch_size': 1,
                'eval_window_batches': 1,
                'population_size': 1,
                'train_split': 0.6,
                'worker_count': 1,
                'tick_delay_ms': 0,
            },
        },
    )
    assert created.status_code == 200
    job_id = created.json()['id']
    started = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'start'})
    assert started.status_code == 200
    client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'stop'})


def test_bots_from_checkpoint_and_labels(client: TestClient) -> None:
    _bootstrap_baselines(client)

    disabled = client.post(
        '/api/v1/bots/from-checkpoint',
        json={
            'job_id': 'disabled',
            'checkpoint_id': 'disabled',
            'bot_version_id': 'candidate-001',
            'policy_type': 'probability_strong',
            'feature_schema_version': 'classic_features_v1',
            'lookahead_policy_version': 'adaptive_v1',
        },
    )
    assert disabled.status_code == 410

    listed = client.get('/api/v1/bots?ruleset_id=classic_v1')
    assert listed.status_code == 200
    assert any(item['bot_version_id'] == 'classic_v1-baseline-strong' for item in listed.json())

    labels = client.patch(
        '/api/v1/bots/classic_v1-baseline-strong/labels',
        json={'is_baseline': True, 'is_legacy': True},
    )
    assert labels.status_code == 200
    assert sorted(labels.json()['tags']) == ['baseline', 'legacy']

    without_legacy = client.get('/api/v1/bots?include_legacy=false')
    assert without_legacy.status_code == 200
    assert all(item['bot_version_id'] != 'classic_v1-baseline-strong' for item in without_legacy.json())


def test_bots_checkpoints_endpoint_filters_by_ruleset(client: TestClient) -> None:
    classic_only = client.get('/api/v1/bots/checkpoints?ruleset_id=classic_v1')
    assert classic_only.status_code == 200
    assert classic_only.json() == []

    all_rows = client.get('/api/v1/bots/checkpoints')
    assert all_rows.status_code == 200
    assert all_rows.json() == []
