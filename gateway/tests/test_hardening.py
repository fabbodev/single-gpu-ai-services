import asyncio

import httpx
from fastapi.testclient import TestClient
import pytest

from app import main
from app.main import app


AUTH = {"Authorization": "Bearer test-bot-token-not-a-real-secret"}
client = TestClient(app, headers=AUTH)


def test_gateway_ready_is_operational_and_does_not_require_bot_key(monkeypatch):
    class FakeDispatcher:
        async def ready(self):
            return {
                "ready": True,
                "state": "idle",
                "epoch": "epoch-1",
                "protocol": 2,
                "reason": None,
            }

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    response = TestClient(app).get("/ready")

    assert response.status_code == 200
    assert response.json()["ready"] is True


def test_gateway_ready_returns_503_when_dispatcher_is_unavailable(monkeypatch):
    class FakeDispatcher:
        async def ready(self):
            raise httpx.ConnectError("dispatcher down")
    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    response = TestClient(app).get("/ready")

    assert response.status_code == 503


def test_ocr_rejects_oversized_upload_before_gpu_acquire(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service):
            events.append(("acquire", service))

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    monkeypatch.setattr(main, "MAX_OCR_UPLOAD_BYTES", 4)

    response = client.post(
        "/v1/documents/read",
        files={"file": ("test.png", b"12345", "image/png")},
    )

    assert response.status_code == 413
    assert events == []


def test_embeddings_rejects_missing_input_before_gpu_acquire(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service):
            events.append(("acquire", service))

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    response = client.post(
        "/v1/embeddings",
        json={"model": "bge-m3"},
    )

    assert response.status_code == 400
    assert events == []
def test_rerank_rejects_empty_query_before_gpu_acquire(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service):
            events.append(("acquire", service))

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    response = client.post(
        "/v1/rerank",
        json={
            "model": "bge-reranker-v2-m3",
            "query": "",
            "documents": ["one"],
        },
    )

    assert response.status_code == 400
    assert events == []


def test_chat_rejects_missing_messages_before_gpu_acquire(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service):
            events.append(("acquire", service))

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    response = client.post(
        "/v1/chat/completions",
        json={"model": "qwen3-8b"},
    )

    assert response.status_code == 400
    assert events == []
def test_stt_rejects_backend_200_without_text_and_releases(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service):
            events.append(("acquire", service))
            return "lease"

        async def release(self, lease):
            events.append(("release", lease))

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    monkeypatch.setattr(main.httpx, "AsyncClient", FakeAsyncClient)

    response = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("sample.wav", b"audio", "audio/wav")},
    )

    assert response.status_code == 502
    assert events == [
        ("acquire", "stt"),
        ("release", "lease"),
    ]
def test_ocr_rejects_backend_200_with_wrong_schema_and_releases(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service):
            events.append(("acquire", service))
            return "lease"

        async def release(self, lease):
            events.append(("release", lease))

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {}

    class FakeHTTPClient:
        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    monkeypatch.setattr(main, "http_client", FakeHTTPClient())

    response = client.post(
        "/v1/documents/read",
        files={"file": ("test.png", b"image", "image/png")},
    )

    assert response.status_code == 502
    assert events == [
        ("acquire", "ocr"),
        ("release", "lease"),
    ]


@pytest.mark.asyncio
async def test_capacity_limiter_rejects_when_full():
    from app.limits import RequestCapacityLimiter

    limiter = RequestCapacityLimiter(1)
    assert await limiter.try_acquire() is True
    assert await limiter.try_acquire() is False
    limiter.release()
    assert await limiter.try_acquire() is True
