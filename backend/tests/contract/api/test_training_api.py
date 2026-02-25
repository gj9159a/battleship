import time

from fastapi.testclient import TestClient


def _fast_params(**overrides: float | int) -> dict[str, float | int]:
    params: dict[str, float | int] = {
        'microbatch_size': 4,
        'eval_window_batches': 1,
        'checkpoint_interval_batches': 1,
        'population_size': 2,
        'train_split': 0.6,
        'worker_count': 1,
        'quality_gate_games': 4,
        'target_score': 1.0,
        'early_stop_plateau_windows': 1000,
        'min_windows_before_early_stop': 1,
        'tick_delay_ms': 0,
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


def _wait_for_windows(client: TestClient, job_id: str, min_windows: int, timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f'/api/v1/training/jobs/{job_id}')
        assert response.status_code == 200
        payload = response.json()
        if payload['progress']['windows_done'] >= min_windows:
            return payload
        time.sleep(0.02)
    raise AssertionError(f'job {job_id} did not reach windows_done>={min_windows}')


def test_training_job_lifecycle_rest(client: TestClient) -> None:
    created = client.post(
        '/api/v1/training/jobs',
        json={
            'ruleset_id': 'classic_v1',
            'seed': 42,
            'params': _fast_params(tick_delay_ms=2),
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
    assert paused['progress']['games_played'] % 4 == 0

    resumed = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'resume'})
    assert resumed.status_code == 200
    assert resumed.json()['lifecycle_state'] == 'Running'

    stopping = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'stop'})
    assert stopping.status_code == 200
    assert stopping.json()['lifecycle_state'] in ('Stopping', 'Stopped')

    stopped = _wait_for_state(client, job_id, 'Stopped')
    assert stopped['stop_reason'] == 'stopped_by_user'


def test_training_job_seed_is_random_when_not_provided(client: TestClient) -> None:
    created = client.post(
        '/api/v1/training/jobs',
        json={
            'ruleset_id': 'classic_v1',
            'params': _fast_params(),
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert isinstance(payload['seed'], int)
    assert payload['seed'] > 0


def test_training_window_metrics_endpoint_returns_full_epoch_history(client: TestClient) -> None:
    created = client.post(
        '/api/v1/training/jobs',
        json={
            'ruleset_id': 'classic_v1',
            'seed': 99,
            'params': _fast_params(
                microbatch_size=1,
                eval_window_batches=1,
                checkpoint_interval_batches=1000,
                tick_delay_ms=0,
            ),
        },
    )
    assert created.status_code == 200
    job_id = created.json()['id']

    started = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'start'})
    assert started.status_code == 200

    running = _wait_for_windows(client, job_id, min_windows=4, timeout=12.0)
    assert running['lifecycle_state'] == 'Running'

    response = client.get(f'/api/v1/training/jobs/{job_id}/windows')
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) >= 4

    windows = [int(row['window']) for row in rows]
    assert windows == sorted(windows)
    assert windows[0] == 1
    assert windows == list(range(1, windows[-1] + 1))

    for row in rows:
        assert row['window_evaluated'] is True
        assert 'promotion_tested' in row
        assert 'promotion_passed' in row
        assert 'promotion_rank' in row

    stopping = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'stop'})
    assert stopping.status_code == 200
    stopped = _wait_for_state(client, job_id, 'Stopped')
    assert stopped['stop_reason'] == 'stopped_by_user'


def test_training_job_exposes_autoevolve_params_and_progress_fields(client: TestClient) -> None:
    created = client.post(
        '/api/v1/training/jobs',
        json={
            'ruleset_id': 'classic_v1',
            'seed': 42,
            'params': _fast_params(
                autoevolve_enabled=False,
                meta_plateau_patience_cycles=5,
                strictness_max_level=2,
            ),
        },
    )
    assert created.status_code == 200
    payload = created.json()

    assert payload['params']['autoevolve_enabled'] is False
    assert payload['params']['meta_plateau_patience_cycles'] == 5
    assert payload['params']['strictness_max_level'] == 2

    assert payload['progress']['cycle_index'] == 0
    assert payload['progress']['strictness_level'] == 0
    assert payload['progress']['meta_plateau_counter'] == 0
    assert payload['progress']['champion_gate_lcb'] == 0.0
    assert isinstance(payload['progress']['eval_protocol_hash'], str)
    assert len(payload['progress']['eval_protocol_hash']) == 16
    assert 'selection_robust_score_candidate' in payload['progress']
    assert 'selection_robust_score_incumbent' in payload['progress']
    assert 'selection_noninferiority_passed' in payload['progress']
    assert 'selection_attack_efficiency_candidate' in payload['progress']
    assert 'selection_tiebreak_used' in payload['progress']
    assert payload['progress']['selection_decision_reason'] == 'unknown'
    assert payload['progress']['elite_candidates_evaluated'] >= 0
    assert 'elite_selected_candidate_index' in payload['progress']
    assert 'elite_selection_reason' in payload['progress']
    assert 'sigma_mean' in payload['progress']
    assert 'sigma_min' in payload['progress']
    assert 'sigma_max' in payload['progress']
    assert payload['progress']['search_policy'] == 'sep_cma_es_lite_v1'
    assert 'cma_sigma' in payload['progress']
    assert 'cma_diag_mean' in payload['progress']
    assert 'cma_diag_min' in payload['progress']
    assert 'cma_diag_max' in payload['progress']
    assert 'cma_generation' in payload['progress']
    assert 'cma_mean_incumbent_l2' in payload['progress']
    assert 'cma_parent_mu' in payload['progress']
    assert 'cma_mueff' in payload['progress']
    assert payload['progress']['search_state_bootstrapped'] is False
    assert payload['progress']['restart_count'] >= 0
    assert 'last_restart_reason' in payload['progress']
    assert 'last_restart_anchor_score' in payload['progress']
    assert 'last_restart_window' in payload['progress']
    assert 'elite_fallback_used' in payload['progress']
    assert 'last_promotion_tested' in payload['progress']
    assert 'last_promotion_passed' in payload['progress']
    assert 'last_promotion_rank' in payload['progress']


def test_training_checkpoints_save_and_load(client: TestClient) -> None:
    created = client.post(
        '/api/v1/training/jobs',
        json={
            'ruleset_id': 'classic_v1',
            'params': _fast_params(microbatch_size=2),
        },
    )
    job_id = created.json()['id']

    started = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'start'})
    assert started.status_code == 200

    checkpoints = client.get(f'/api/v1/training/jobs/{job_id}/checkpoints')
    assert checkpoints.status_code == 200
    assert checkpoints.json() == []

    client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'pause'})
    _wait_for_state(client, job_id, 'Paused')

    loaded = client.post(f"/api/v1/training/jobs/{job_id}/resume-from/disabled")
    assert loaded.status_code == 410


def test_training_does_not_auto_complete_on_weak_or_early_plateau(client: TestClient) -> None:
    created = client.post(
        '/api/v1/training/jobs',
        json={
            'ruleset_id': 'classic_v1',
            'seed': 7,
            'params': _fast_params(
                microbatch_size=1,
                population_size=1,
                checkpoint_interval_batches=1000,
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

    running = _wait_for_windows(client, job_id, min_windows=2, timeout=12.0)
    assert running['lifecycle_state'] == 'Running'
    assert running['stop_reason'] is None

    stopping = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'stop'})
    assert stopping.status_code == 200
    stopped = _wait_for_state(client, job_id, 'Stopped')
    assert stopped['stop_reason'] == 'stopped_by_user'


def test_training_does_not_auto_complete_when_early_stop_thresholds_are_low(client: TestClient) -> None:
    created = client.post(
        '/api/v1/training/jobs',
        json={
            'ruleset_id': 'classic_v1',
            'seed': 77,
            'params': _fast_params(
                microbatch_size=1,
                population_size=1,
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

    running = _wait_for_windows(client, job_id, min_windows=2, timeout=12.0)
    assert running['lifecycle_state'] == 'Running'
    assert running['stop_reason'] is None

    stopping = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'stop'})
    assert stopping.status_code == 200
    stopped = _wait_for_state(client, job_id, 'Stopped')
    assert stopped['stop_reason'] == 'stopped_by_user'


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
    metrics_batches: list[int] = []
    with client.websocket_connect('/api/v1/ws') as ws:
        response = client.post(f'/api/v1/training/jobs/{job_id}/commands', json={'command': 'start'})
        assert response.status_code == 200

        for _ in range(20):
            event = ws.receive_json()
            if event['entity_id'] == job_id:
                seen_types.add(event['event_type'])
                if event['event_type'] == 'training.metrics':
                    metrics_batches.append(int(event['payload'].get('batches_done', 0)))
                    assert 'selection_robust_score_candidate' in event['payload']
                    assert 'selection_robust_score_incumbent' in event['payload']
                    assert 'selection_noninferiority_passed' in event['payload']
                    assert 'selection_attack_efficiency_candidate' in event['payload']
                    assert 'selection_tiebreak_used' in event['payload']
                    assert 'selection_decision_reason' in event['payload']
                    assert 'elite_candidates_evaluated' in event['payload']
                    assert 'elite_selected_candidate_index' in event['payload']
                    assert 'elite_selection_reason' in event['payload']
                    assert 'sigma_mean' in event['payload']
                    assert 'sigma_min' in event['payload']
                    assert 'sigma_max' in event['payload']
                    assert event['payload']['search_policy'] == 'sep_cma_es_lite_v1'
                    assert 'cma_sigma' in event['payload']
                    assert 'cma_diag_mean' in event['payload']
                    assert 'cma_diag_min' in event['payload']
                    assert 'cma_diag_max' in event['payload']
                    assert 'cma_generation' in event['payload']
                    assert 'cma_mean_incumbent_l2' in event['payload']
                    assert 'cma_parent_mu' in event['payload']
                    assert 'cma_mueff' in event['payload']
                    assert 'search_state_bootstrapped' in event['payload']
                    assert 'restart_count' in event['payload']
                    assert 'last_restart_reason' in event['payload']
                    assert 'last_restart_anchor_score' in event['payload']
                    assert 'last_restart_window' in event['payload']
                    assert 'elite_fallback_used' in event['payload']
            if {'job.lifecycle_changed', 'training.stage_changed', 'training.metrics'}.issubset(seen_types):
                if metrics_batches and max(metrics_batches) >= 1:
                    break

    assert 'job.lifecycle_changed' in seen_types
    assert 'training.stage_changed' in seen_types
    assert 'training.metrics' in seen_types
    assert metrics_batches
    assert max(metrics_batches) >= 1


def test_training_job_accepts_seed_bot_version(client: TestClient) -> None:
    source_job = client.post(
        '/api/v1/training/jobs',
        json={
            'ruleset_id': 'classic_v1',
            'seed': 22,
            'params': _fast_params(microbatch_size=1, population_size=1, tick_delay_ms=0),
        },
    )
    assert source_job.status_code == 200
    source_job_id = source_job.json()['id']
    started = client.post(f'/api/v1/training/jobs/{source_job_id}/commands', json={'command': 'start'})
    assert started.status_code == 200

    _wait_for_windows(client, source_job_id, min_windows=1, timeout=6.0)

    created = client.post(
        '/api/v1/training/jobs',
        json={
            'ruleset_id': 'classic_v1',
            'seed_bot_version_id': 'classic_v1-baseline-strong',
            'seed': 101,
        },
    )

    assert created.status_code == 200
    assert created.json()['seed_bot_version_id'] == 'classic_v1-baseline-strong'


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
            'params': _fast_params(microbatch_size=1, population_size=1, tick_delay_ms=0),
        },
    )
    assert source_job.status_code == 200
    source_job_id = source_job.json()['id']
    started = client.post(f'/api/v1/training/jobs/{source_job_id}/commands', json={'command': 'start'})
    assert started.status_code == 200

    _wait_for_windows(client, source_job_id, min_windows=1, timeout=6.0)

    invalid = client.post(
        '/api/v1/training/jobs',
        json={
            'ruleset_id': 'classic_alt_v2',
            'seed_bot_version_id': 'classic_v1-baseline-strong',
            'seed': 10,
        },
    )
    assert invalid.status_code == 422
