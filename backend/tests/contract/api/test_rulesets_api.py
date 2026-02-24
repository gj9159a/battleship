from fastapi.testclient import TestClient


def test_get_rulesets_returns_classic(client: TestClient) -> None:
    response = client.get('/api/v1/rulesets')

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    classic = next(item for item in payload if item['id'] == 'classic_v1')
    assert classic['fleet'] == [5, 4, 3, 3, 2]
    assert classic['placement_no_touch'] is False
