import httpx
from fastapi.testclient import TestClient

from app import main
from app.main import app

client = TestClient(app)


def test_embeddings_acquires_forwards_and_releases(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service): events.append(("acquire", service))
        async def release(self, service): events.append(("release", service))

    class FakeResponse:
        def raise_for_status(self): pass
        def json(self): return {"object": "list", "data": [{"embedding": [0.1, 0.2], "index": 0}], "model": "bge-m3"}

    class FakeHTTPClient:
        async def post(self, url, json):
            events.append(("post", url, json))
            return FakeResponse()

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    monkeypatch.setattr(main, "http_client", FakeHTTPClient())

    response = client.post("/v1/embeddings", json={"model": "bge-m3", "input": "hello"})
    assert response.status_code == 200
    assert events[0] == ("acquire", "embeddings")
    assert events[-1] == ("release", "embeddings")


def test_embeddings_bad_model_does_not_acquire(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service): events.append(("acquire", service))
        async def release(self, service): events.append(("release", service))

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    response = client.post("/v1/embeddings", json={"model": "wrong", "input": "hello"})
    assert response.status_code == 400
    assert events == []


def test_embeddings_backend_failure_releases(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service): events.append(("acquire", service))
        async def release(self, service): events.append(("release", service))

    class FakeHTTPClient:
        async def post(self, url, json):
            raise httpx.ConnectError("backend down")

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    monkeypatch.setattr(main, "http_client", FakeHTTPClient())
    response = client.post("/v1/embeddings", json={"model": "bge-m3", "input": "hello"})
    assert response.status_code == 502
    assert events == [("acquire", "embeddings"), ("release", "embeddings")]
