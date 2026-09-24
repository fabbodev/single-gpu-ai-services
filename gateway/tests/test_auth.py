from fastapi.testclient import TestClient

from app.main import app


TEST_TOKEN = "test-bot-token-not-a-real-secret"
client = TestClient(app)


def test_health_remains_available_without_client_token():
    response = client.get("/health")
    assert response.status_code == 200


def test_gateway_rejects_missing_bearer_token():
    response = client.get("/v1/models")
    assert response.status_code == 401


def test_gateway_rejects_invalid_bearer_token():
    response = client.get(
        "/v1/models",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


def test_gateway_accepts_valid_bot_token():
    response = client.get(
        "/v1/models",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    )
    assert response.status_code == 200


def test_gateway_records_client_identity_without_logging_token(caplog):
    caplog.set_level("INFO", logger="ai.gateway.auth")
    response = client.get(
        "/v1/models",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    )

    assert response.status_code == 200
    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert "client_id=test-bot" in combined
    assert TEST_TOKEN not in combined


def test_gateway_auth_logger_emits_info_in_production():
    import logging
    from app import main

    assert main.auth_logger.isEnabledFor(logging.INFO)


def test_gateway_auth_logger_has_runtime_handler():
    from app import main

    assert main.auth_logger.handlers
