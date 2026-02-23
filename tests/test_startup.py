from fastapi.testclient import TestClient

from mitra_app.main import app


def test_app_startup() -> None:
    with TestClient(app) as client:
        r = client.get("/healthz")
        assert r.status_code == 200
