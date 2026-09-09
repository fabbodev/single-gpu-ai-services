from fastapi.testclient import TestClient

from app import main
from app.main import app

client = TestClient(app)


def test_rerank_acquires_forwards_translates_and_releases(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service):
            events.append(("acquire", service))

        async def release(self, service):
            events.append(("release", service))

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return [
                {"index": 0, "score": 0.95},
                {"index": 2, "score": 0.10},
                {"index": 1, "score": 0.01},
            ]

    class FakeHTTPClient:
        async def post(self, url, json):
            events.append(("post", url, json))
            return FakeResponse()

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    monkeypatch.setattr(main, "http_client", FakeHTTPClient())

    response = client.post(
        "/v1/rerank",
        json={
            "model": "bge-reranker-v2-m3",
            "query": "¿De qué color es el cielo?",
            "documents": [
                "El cielo es azul.",
                "Los gatos son mamíferos.",
                "La nieve es blanca.",
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "model": "bge-reranker-v2-m3",
        "results": [
            {"index": 0, "score": 0.95},
            {"index": 2, "score": 0.10},
            {"index": 1, "score": 0.01},
        ],
    }

    assert events == [
        ("acquire", "reranker"),
        (
            "post",
            "http://ai-reranker:8080/rerank",
            {
                "query": "¿De qué color es el cielo?",
                "texts": [
                    "El cielo es azul.",
                    "Los gatos son mamíferos.",
                    "La nieve es blanca.",
                ],
            },
        ),
        ("release", "reranker"),
    ]


def test_rerank_rejects_unsupported_model_without_acquiring(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service):
            events.append(("acquire", service))

        async def release(self, service):
            events.append(("release", service))

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())

    response = client.post(
        "/v1/rerank",
        json={
            "model": "not-reranker",
            "query": "hola",
            "documents": ["uno", "dos"],
        },
    )

    assert response.status_code == 400
    assert events == []


def test_rerank_backend_failure_releases(monkeypatch):
    import httpx

    events = []

    class FakeDispatcher:
        async def acquire(self, service):
            events.append(("acquire", service))

        async def release(self, service):
            events.append(("release", service))

    class FakeHTTPClient:
        async def post(self, url, json):
            events.append(("post", url))
            raise httpx.ConnectError("backend down")

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    monkeypatch.setattr(main, "http_client", FakeHTTPClient())

    response = client.post(
        "/v1/rerank",
        json={
            "model": "bge-reranker-v2-m3",
            "query": "hola",
            "documents": ["uno", "dos"],
        },
    )

    assert response.status_code == 502
    assert events == [
        ("acquire", "reranker"),
        ("post", "http://ai-reranker:8080/rerank"),
        ("release", "reranker"),
    ]
