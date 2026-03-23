from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_outbox_status_endpoint_shape() -> None:
    response = client.get("/internal/events/outbox/status")
    assert response.status_code == 200

    payload = response.json()
    assert "backend" in payload
    assert "counts" in payload
    assert "backlog_age_seconds" in payload
    assert "retry_policy" in payload
