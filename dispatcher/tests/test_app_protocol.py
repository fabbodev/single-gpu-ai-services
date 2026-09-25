from fastapi.testclient import TestClient

import app as dispatcher_app


PRODUCTION_STARTUP_TIMEOUT = dispatcher_app.dispatcher.startup_timeout
PRODUCTION_HEALTH_ATTEMPTS = dispatcher_app.dispatcher._engine_manager.health_attempts
PRODUCTION_HEALTH_INTERVAL = dispatcher_app.dispatcher._engine_manager.health_interval
dispatcher_app.dispatcher.close()


class FakeDispatcher:
    epoch = "epoch-1"

    def __init__(self):
        self.calls = []

    def ready(self):
        return {
            "ready": True,
            "state": "idle",
            "epoch": self.epoch,
            "reason": None,
        }

    def submit(self, service, request_id, epoch, *, wait_timeout):
        self.calls.append(
            ("submit", service, request_id, epoch, wait_timeout)
        )
        return {
            "request_id": request_id,
            "service": service,
            "state": "queued",
            "error": None,
        }
    def get_lease(self, request_id, epoch):
        self.calls.append(("get", request_id, epoch))
        return {
            "request_id": request_id,
            "service": "llm",
            "state": "active",
            "error": None,
        }

    def release(self, *args):
        self.calls.append(("release",) + args)
        return {
            "request_id": args[1] if len(args) > 1 else "missing",
            "service": "llm",
            "state": "stopping",
            "error": None,
        }

    def cancel(self, *args):
        self.calls.append(("cancel",) + args)
        return {
            "request_id": args[1],
            "service": "llm",
            "state": "cancelled",
            "error": None,
        }


def test_production_health_window_covers_startup_timeout():
    assert PRODUCTION_HEALTH_ATTEMPTS * PRODUCTION_HEALTH_INTERVAL >= PRODUCTION_STARTUP_TIMEOUT


def make_client():
    fake = FakeDispatcher()
    dispatcher_app.dispatcher = fake
    return TestClient(dispatcher_app.app, headers={"X-AI-Internal-Token": "test-internal-dispatcher-token-0123456789abcdef"}), fake


def test_ready_exposes_epoch_and_readiness():
    client, _ = make_client()
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert response.json()["epoch"] == "epoch-1"


def test_acquire_is_brief_and_requires_identity():
    client, fake = make_client()
    response = client.post(
        "/acquire/llm",
        json={
            "request_id": "req-1",
            "epoch": "epoch-1",
            "wait_timeout": 30,
        },
    )

    assert response.status_code == 202
    assert response.json()["state"] == "queued"
    assert fake.calls == [
        ("submit", "llm", "req-1", "epoch-1", 30.0)
    ]
def test_lease_status_is_polled_by_request_id():
    client, fake = make_client()
    response = client.get(
        "/leases/req-1",
        params={"epoch": "epoch-1"},
    )

    assert response.status_code == 200
    assert response.json()["state"] == "active"
    assert fake.calls == [("get", "req-1", "epoch-1")]


def test_release_requires_request_identity():
    client, fake = make_client()
    response = client.post(
        "/release/llm",
        json={"request_id": "req-1", "epoch": "epoch-1"},
    )

    assert response.status_code == 202
    assert fake.calls == [
        ("release", "llm", "req-1", "epoch-1")
    ]


def test_cancel_endpoint_is_idempotent_by_request_id():
    client, fake = make_client()
    response = client.post(
        "/cancel/llm",
        json={"request_id": "req-1", "epoch": "epoch-1"},
    )

    assert response.status_code == 200
    assert response.json()["state"] == "cancelled"
    assert fake.calls == [
        ("cancel", "llm", "req-1", "epoch-1")
    ]
