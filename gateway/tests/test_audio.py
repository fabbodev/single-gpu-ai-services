import httpx
from fastapi.testclient import TestClient

from app import main
from app.main import app

client = TestClient(app)


def test_models_lists_reference_models():
    response = client.get("/v1/models")
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["data"]}
    assert {"qwen3-8b", "faster-whisper-large-v3", "coqui-es-css10-vits", "bge-m3", "bge-reranker-v2-m3", "paddleocr-vl-1.6"} <= ids


def test_stt_acquires_and_releases(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service): events.append(("acquire", service))
        async def release(self, service): events.append(("release", service))

    class FakeResponse:
        def raise_for_status(self): pass
        def json(self): return {"text": "hello"}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, files, data):
            assert data["model"] == "Systran/faster-whisper-large-v3"
            events.append(("post", url))
            return FakeResponse()

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    monkeypatch.setattr(main.httpx, "AsyncClient", FakeAsyncClient)
    response = client.post(
        "/v1/audio/transcriptions",
        data={"model": "faster-whisper-large-v3", "language": "en"},
        files={"file": ("sample.wav", b"audio", "audio/wav")},
    )
    assert response.status_code == 200
    assert response.json() == {"text": "hello"}
    assert events == [
        ("acquire", "stt"),
        ("post", "http://ai-stt:8000/v1/audio/transcriptions"),
        ("release", "stt"),
    ]


def test_stt_bad_model_does_not_acquire(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service): events.append(service)
        async def release(self, service): pass

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    response = client.post(
        "/v1/audio/transcriptions",
        data={"model": "wrong"},
        files={"file": ("sample.wav", b"audio", "audio/wav")},
    )
    assert response.status_code == 400
    assert events == []


def test_tts_acquires_and_releases(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service): events.append(("acquire", service))
        async def release(self, service): events.append(("release", service))

    class FakeResponse:
        content = b"RIFF-test"
        def raise_for_status(self): pass

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, params):
            assert params["text"] == "Hola"
            events.append(("post", url))
            return FakeResponse()

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    monkeypatch.setattr(main.httpx, "AsyncClient", FakeAsyncClient)
    response = client.post(
        "/v1/audio/speech",
        json={"model": "coqui-es-css10-vits", "input": "Hola", "response_format": "wav"},
    )
    assert response.status_code == 200
    assert response.content == b"RIFF-test"
    assert events == [
        ("acquire", "tts"),
        ("post", "http://ai-tts:5002/api/tts"),
        ("release", "tts"),
    ]


def test_tts_rejects_missing_input_and_wrong_format(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service): events.append(service)
        async def release(self, service): pass

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    missing = client.post("/v1/audio/speech", json={"model": "coqui-es-css10-vits"})
    wrong_format = client.post(
        "/v1/audio/speech",
        json={"model": "coqui-es-css10-vits", "input": "Hola", "response_format": "mp3"},
    )
    assert missing.status_code == 400
    assert wrong_format.status_code == 400
    assert events == []


def test_tts_backend_failure_releases(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service): events.append(("acquire", service))
        async def release(self, service): events.append(("release", service))

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, params): raise httpx.ConnectError("backend down")

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    monkeypatch.setattr(main.httpx, "AsyncClient", FakeAsyncClient)
    response = client.post(
        "/v1/audio/speech",
        json={"model": "coqui-es-css10-vits", "input": "Hola", "response_format": "wav"},
    )
    assert response.status_code == 502
    assert events == [("acquire", "tts"), ("release", "tts")]
