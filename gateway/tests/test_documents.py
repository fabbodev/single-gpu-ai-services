import base64
import httpx
from fastapi.testclient import TestClient

from app import main
from app.main import app

client = TestClient(app)


def test_documents_image_acquires_forwards_and_releases(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service): events.append(("acquire", service))
        async def release(self, service): events.append(("release", service))

    class FakeResponse:
        def raise_for_status(self): pass
        def json(self):
            return {"result": {"layoutParsingResults": [{"markdown": {"text": "OCR OK"}}]}}

    class FakeHTTPClient:
        async def post(self, url, json):
            events.append(("post", url, json))
            return FakeResponse()

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    monkeypatch.setattr(main, "http_client", FakeHTTPClient())
    payload = b"image-bytes"
    response = client.post(
        "/v1/documents/read",
        data={"model": "paddleocr-vl-1.6"},
        files={"file": ("test.png", payload, "image/png")},
    )
    assert response.status_code == 200
    assert response.json()["text"] == "OCR OK"
    assert events[0] == ("acquire", "ocr")
    assert events[1][2]["file"] == base64.b64encode(payload).decode()
    assert events[1][2]["fileType"] == 1
    assert events[-1] == ("release", "ocr")


def test_documents_pdf_joins_pages(monkeypatch):
    class FakeDispatcher:
        async def acquire(self, service): pass
        async def release(self, service): pass

    class FakeResponse:
        def raise_for_status(self): pass
        def json(self):
            return {"result": {"layoutParsingResults": [
                {"markdown": {"text": "PAGE ONE"}},
                {"markdown": {"text": "PAGE TWO"}},
            ]}}

    class FakeHTTPClient:
        async def post(self, url, json):
            assert json["fileType"] == 0
            return FakeResponse()

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    monkeypatch.setattr(main, "http_client", FakeHTTPClient())
    response = client.post(
        "/v1/documents/read",
        files={"file": ("test.pdf", b"pdf", "application/pdf")},
    )
    assert response.status_code == 200
    assert response.json()["text"] == "PAGE ONE\n\nPAGE TWO"


def test_documents_bad_model_and_mime_do_not_acquire(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service): events.append(service)
        async def release(self, service): pass

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    bad_model = client.post(
        "/v1/documents/read",
        data={"model": "wrong"},
        files={"file": ("test.png", b"x", "image/png")},
    )
    bad_mime = client.post(
        "/v1/documents/read",
        files={"file": ("test.txt", b"x", "text/plain")},
    )
    assert bad_model.status_code == 400
    assert bad_mime.status_code == 400
    assert events == []


def test_documents_backend_failure_releases(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service): events.append(("acquire", service))
        async def release(self, service): events.append(("release", service))

    class FakeHTTPClient:
        async def post(self, url, json): raise httpx.ConnectError("backend down")

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    monkeypatch.setattr(main, "http_client", FakeHTTPClient())
    response = client.post(
        "/v1/documents/read",
        files={"file": ("test.png", b"x", "image/png")},
    )
    assert response.status_code == 502
    assert events == [("acquire", "ocr"), ("release", "ocr")]
