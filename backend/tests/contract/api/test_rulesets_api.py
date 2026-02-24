from fastapi.testclient import TestClient


def test_get_rulesets_returns_classic(client: TestClient) -> None:
    response = client.get('/api/v1/rulesets')

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert any(item['id'] == 'classic_v1' for item in payload)
