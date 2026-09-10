import httpx
from fastapi.testclient import TestClient

from app import main
from app.main import app

client = TestClient(app)


def test_rerank_acquires_forwards_and_releases(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service): events.append(("acquire", service))
        async def release(self, service): events.append(("release", service))

    class FakeResponse:
        def raise_for_status(self): pass
        def json(self): return [{"index": 0, "score": 0.95}]

    class FakeHTTPClient:
        async def post(self, url, json):
            events.append(("post", url, json))
            return FakeResponse()

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    monkeypatch.setattr(main, "http_client", FakeHTTPClient())
    response = client.post(
        "/v1/rerank",
        json={"model": "bge-reranker-v2-m3", "query": "sky color", "documents": ["blue sky", "cat"]},
    )
    assert response.status_code == 200
    assert response.json()["results"][0]["index"] == 0
    assert events[0] == ("acquire", "reranker")
    assert events[-1] == ("release", "reranker")


def test_rerank_bad_model_does_not_acquire(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service): events.append(("acquire", service))
        async def release(self, service): events.append(("release", service))

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    response = client.post("/v1/rerank", json={"model": "wrong", "query": "x", "documents": ["y"]})
    assert response.status_code == 400
    assert events == []


def test_rerank_backend_failure_releases(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service): events.append(("acquire", service))
        async def release(self, service): events.append(("release", service))

    class FakeHTTPClient:
        async def post(self, url, json): raise httpx.ConnectError("backend down")

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    monkeypatch.setattr(main, "http_client", FakeHTTPClient())
    response = client.post(
        "/v1/rerank",
        json={"model": "bge-reranker-v2-m3", "query": "x", "documents": ["y"]},
    )
    assert response.status_code == 502
    assert events == [("acquire", "reranker"), ("release", "reranker")]
