import pytest
from fastapi.testclient import TestClient

from app.rulesets import catalog


@pytest.fixture(autouse=True)
def reset_ruleset_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog, "_RULESETS", {catalog.CLASSIC_V1.id: catalog.CLASSIC_V1}.copy())
    monkeypatch.setattr(catalog, "_ARCHIVED_RULESET_IDS", set())
    monkeypatch.setattr(catalog, "_ACTIVE_RULESET_ID", catalog.CLASSIC_V1.id)


def test_get_rulesets_returns_classic(client: TestClient) -> None:
    response = client.get('/api/v1/rulesets')

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    classic = next(item for item in payload if item['id'] == 'classic_v1')
    assert classic['fleet'] == [5, 4, 3, 3, 2]
    assert classic['placement_no_touch'] is False
    assert classic['is_active'] is True
    assert classic['is_archived'] is False


def test_ruleset_crud_lifecycle(client: TestClient) -> None:
    create_response = client.post(
        '/api/v1/rulesets',
        json={
            'id': 'classic_dense_v2',
            'name': 'Classic Dense v2',
            'board_size': 10,
            'fleet': [5, 4, 3, 3, 2],
            'placement_no_touch': False,
            'extra_turn_on_hit': True,
        },
    )
    assert create_response.status_code == 200
    assert create_response.json()['id'] == 'classic_dense_v2'

    patch_response = client.patch(
        '/api/v1/rulesets/classic_dense_v2',
        json={
            'name': 'Classic Dense v2 tuned',
            'fleet': [5, 4, 3, 2, 2],
        },
    )
    assert patch_response.status_code == 200
    assert patch_response.json()['name'] == 'Classic Dense v2 tuned'
    assert patch_response.json()['fleet'] == [5, 4, 3, 2, 2]

    activate_response = client.post('/api/v1/rulesets/classic_dense_v2/activate')
    assert activate_response.status_code == 200
    assert activate_response.json()['is_active'] is True
    active_response = client.get('/api/v1/rulesets/active')
    assert active_response.status_code == 200
    assert active_response.json()['id'] == 'classic_dense_v2'

    archive_response = client.post('/api/v1/rulesets/classic_v1/archive')
    assert archive_response.status_code == 200
    assert archive_response.json()['is_archived'] is True

    list_response = client.get('/api/v1/rulesets')
    assert list_response.status_code == 200
    ids = [item['id'] for item in list_response.json()]
    assert 'classic_dense_v2' in ids
    assert 'classic_v1' not in ids

    list_with_archived = client.get('/api/v1/rulesets?include_archived=true')
    assert list_with_archived.status_code == 200
    archived_row = next(item for item in list_with_archived.json() if item['id'] == 'classic_v1')
    assert archived_row['is_archived'] is True

    clone_response = client.post(
        '/api/v1/rulesets/classic_dense_v2/clone',
        json={'new_id': 'classic_dense_v2_clone', 'new_name': 'Classic Dense v2 clone'},
    )
    assert clone_response.status_code == 200
    assert clone_response.json()['id'] == 'classic_dense_v2_clone'


def test_archive_active_ruleset_rejected(client: TestClient) -> None:
    response = client.post('/api/v1/rulesets/classic_v1/archive')

    assert response.status_code == 409
