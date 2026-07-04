from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        upload_dir=tmp_path / "uploads",
        AI_PROVIDER="fake",
        cors_origins=["http://localhost:5173"],
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def seller(client: TestClient):
    response = client.post(
        "/sellers",
        json={"name": "علی رضایی", "mobile": "09120000000", "shop_name": "فروشگاه تست"},
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def batch(client: TestClient, seller: dict):
    response = client.post("/batches", json={"seller_id": seller["id"]})
    assert response.status_code == 201
    return response.json()
