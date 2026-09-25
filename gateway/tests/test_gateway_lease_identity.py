import httpx
from fastapi.testclient import TestClient

from app import main
from app.dispatcher_client import LeaseHandle
from app.main import app


client = TestClient(app, headers={"Authorization": "Bearer test-bot-token-not-a-real-secret"})


def test_chat_releases_exact_lease_handle(monkeypatch):
    lease = LeaseHandle("req-1", "llm", "epoch-1")
    events = []

    class FakeDispatcher:
        async def acquire(self, service):
            events.append(("acquire", service))
            return lease

        async def release(self, handle):
            events.append(("release", handle))

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeHTTPClient:
        async def post(self, url, json):
            events.append(("post", url))
            return FakeResponse()

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    monkeypatch.setattr(main, "http_client", FakeHTTPClient())

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "qwen3-8b",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 200
    assert events == [
        ("acquire", "llm"),
        ("post", "http://ai-llm:8080/v1/chat/completions"),
        ("release", lease),
    ]
