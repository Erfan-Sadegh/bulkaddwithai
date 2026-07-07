from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_frontend_static_files_are_served_after_api_routes(tmp_path: Path):
    frontend_dist = tmp_path / "dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text('<div id="root"></div>', encoding="utf-8")

    app = create_app(
        Settings(
            DATABASE_URL="sqlite:///:memory:",
            UPLOAD_DIR=tmp_path / "uploads",
            FRONTEND_DIST_DIR=frontend_dist,
            AI_PROVIDER="fake",
        )
    )
    client = TestClient(app)

    root = client.get("/")
    admin = client.get("/admin")
    health = client.get("/health")

    assert root.status_code == 200
    assert '<div id="root"></div>' in root.text
    assert admin.status_code == 200
    assert '<div id="root"></div>' in admin.text
    assert health.status_code == 200
    assert health.json() == {"ok": True}
