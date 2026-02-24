from fastapi.testclient import TestClient


def test_health_endpoint(client: TestClient) -> None:
    response = client.get('/api/v1/health')

    assert response.status_code == 200
    payload = response.json()
    assert payload['status'] == 'ok'
    assert payload['service'] == 'battleship-backend'
    assert isinstance(payload['ts'], str)


def test_health_endpoint_cors_preflight(client: TestClient) -> None:
    response = client.options(
        '/api/v1/health',
        headers={
            'Origin': 'http://localhost:5173',
            'Access-Control-Request-Method': 'GET',
        },
    )

    assert response.status_code == 200
    assert response.headers['access-control-allow-origin'] == 'http://localhost:5173'
