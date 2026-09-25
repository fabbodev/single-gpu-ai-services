from fastapi.testclient import TestClient

import app as dispatcher_app


TEST_INTERNAL_TOKEN = "test-internal-dispatcher-token-0123456789abcdef"
client = TestClient(dispatcher_app.app)


def test_dispatcher_health_is_available_without_internal_token():
    response = client.get("/health")
    assert response.status_code == 200


def test_dispatcher_ready_rejects_missing_internal_token():
    response = client.get("/ready")
    assert response.status_code == 401


def test_dispatcher_ready_rejects_wrong_internal_token():
    response = client.get(
        "/ready",
        headers={"X-AI-Internal-Token": "wrong"},
    )
    assert response.status_code == 401


def test_dispatcher_ready_accepts_shared_internal_token():
    response = client.get(
        "/ready",
        headers={"X-AI-Internal-Token": TEST_INTERNAL_TOKEN},
    )
    assert response.status_code == 200
