from fastapi.testclient import TestClient

from app import main
from app.main import app

client = TestClient(app)


def test_embeddings_acquires_forwards_and_releases(monkeypatch):
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
            return {
                "object": "list",
                "data": [
                    {
                        "object": "embedding",
                        "embedding": [0.1, 0.2, 0.3],
                        "index": 0,
                    }
                ],
                "model": "bge-m3",
                "usage": {
                    "prompt_tokens": 4,
                    "total_tokens": 4,
                },
            }

    class FakeHTTPClient:
        async def post(self, url, json):
            events.append(("post", url, json))
            return FakeResponse()

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    monkeypatch.setattr(main, "http_client", FakeHTTPClient())

    response = client.post(
        "/v1/embeddings",
        json={
            "model": "bge-m3",
            "input": "El cielo es azul.",
        },
    )

    assert response.status_code == 200
    assert response.json()["model"] == "bge-m3"
    assert response.json()["data"][0]["embedding"] == [0.1, 0.2, 0.3]

    assert events == [
        ("acquire", "embeddings"),
        (
            "post",
            "http://ai-embeddings:8080/v1/embeddings",
            {
                "model": "bge-m3",
                "input": "El cielo es azul.",
            },
        ),
        ("release", "embeddings"),
    ]


def test_embeddings_rejects_unsupported_model_without_acquiring(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service):
            events.append(("acquire", service))

        async def release(self, service):
            events.append(("release", service))

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())

    response = client.post(
        "/v1/embeddings",
        json={
            "model": "not-bge",
            "input": "hola",
        },
    )

    assert response.status_code == 400
    assert events == []


def test_embeddings_backend_failure_releases(monkeypatch):
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
        "/v1/embeddings",
        json={
            "model": "bge-m3",
            "input": "hola",
        },
    )

    assert response.status_code == 502
    assert events == [
        ("acquire", "embeddings"),
        ("post", "http://ai-embeddings:8080/v1/embeddings"),
        ("release", "embeddings"),
    ]
