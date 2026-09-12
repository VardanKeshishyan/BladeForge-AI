from fastapi.testclient import TestClient

from app.main import app


def test_jobs_require_authentication() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/jobs")
    assert response.status_code == 401
    payload = response.json()
    assert payload["error"]["code"] == "authentication_required"
    assert payload["error"]["request_id"]
