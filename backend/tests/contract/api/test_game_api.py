from fastapi.testclient import TestClient


def test_create_game_session_and_shoot(client: TestClient) -> None:
    create_payload = {
        'ruleset_id': 'classic_v1',
        'first_player': 0,
    }

    created = client.post('/api/v1/game/sessions', json=create_payload)
    assert created.status_code == 200
    session_id = created.json()['id']
    assert created.json()['lifecycle_state'] == 'running'
    assert len(created.json()['player_placements']) == 5
    assert 'opponent_bot_version_id' in created.json()

    shot = client.post(f'/api/v1/game/sessions/{session_id}/shots', json={'row': 0, 'col': 0})
    assert shot.status_code == 200
    assert shot.json()['outcome'] in {'miss', 'hit', 'sunk'}

    state = client.get(f'/api/v1/game/sessions/{session_id}')
    assert state.status_code == 200
    assert len(state.json()['shots']) == 1


def test_create_game_session_unknown_ruleset(client: TestClient) -> None:
    response = client.post(
        '/api/v1/game/sessions',
        json={
            'ruleset_id': 'unknown_ruleset',
            'first_player': 0,
        },
    )
    assert response.status_code == 404


def test_shot_validation_rejects_out_of_bounds(client: TestClient) -> None:
    create_payload = {
        'ruleset_id': 'classic_v1',
        'first_player': 0,
    }
    created = client.post('/api/v1/game/sessions', json=create_payload)
    session_id = created.json()['id']

    response = client.post(f'/api/v1/game/sessions/{session_id}/shots', json={'row': 10, 'col': 10})
    assert response.status_code == 422
