import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("BATTLESHIP_DATA_DIR", str(tmp_path / ".data"))
    return TestClient(create_app())
