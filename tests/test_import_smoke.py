from fastapi.testclient import TestClient

from mitra_app.main import app


def test_import_and_healthz_smoke() -> None:
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
