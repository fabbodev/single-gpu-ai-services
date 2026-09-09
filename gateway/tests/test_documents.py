import base64
import httpx
from fastapi.testclient import TestClient

from app import main
from app.main import app


client = TestClient(app)


def test_documents_read_image_acquires_forwards_and_releases(monkeypatch):
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
                "errorCode": 0,
                "errorMsg": "Success",
                "result": {
                    "layoutParsingResults": [
                        {"markdown": {"text": "## PRUEBA OCR AZUL 7", "images": {}}}
                    ]
                },
            }

    class FakeHTTPClient:
        async def post(self, url, json):
            events.append(("post", url, json))
            return FakeResponse()

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    monkeypatch.setattr(main, "http_client", FakeHTTPClient())

    file_bytes = b"fake-png-bytes"
    response = client.post(
        "/v1/documents/read",
        data={"model": "paddleocr-vl-1.6"},
        files={"file": ("test.png", file_bytes, "image/png")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "model": "paddleocr-vl-1.6",
        "text": "## PRUEBA OCR AZUL 7",
    }
    assert events == [
        ("acquire", "ocr"),
        (
            "post",
            "http://ai-ocr-api:8080/layout-parsing",
            {
                "file": base64.b64encode(file_bytes).decode(),
                "fileType": 1,
                "visualize": False,
                "restructurePages": False,
            },
        ),
        ("release", "ocr"),
    ]


def test_documents_read_pdf_uses_pdf_file_type_and_joins_pages(monkeypatch):
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
                "errorCode": 0,
                "errorMsg": "Success",
                "result": {
                    "layoutParsingResults": [
                        {"markdown": {"text": "# PAGE ONE", "images": {}}},
                        {"markdown": {"text": "PAGE TWO", "images": {}}},
                    ]
                },
            }

    class FakeHTTPClient:
        async def post(self, url, json):
            events.append(("post", url, json))
            return FakeResponse()

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    monkeypatch.setattr(main, "http_client", FakeHTTPClient())

    file_bytes = b"fake-pdf-bytes"
    response = client.post(
        "/v1/documents/read",
        data={"model": "paddleocr-vl-1.6"},
        files={"file": ("test.pdf", file_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "model": "paddleocr-vl-1.6",
        "text": "# PAGE ONE\n\nPAGE TWO",
    }
    assert events == [
        ("acquire", "ocr"),
        (
            "post",
            "http://ai-ocr-api:8080/layout-parsing",
            {
                "file": base64.b64encode(file_bytes).decode(),
                "fileType": 0,
                "visualize": False,
                "restructurePages": False,
            },
        ),
        ("release", "ocr"),
    ]


def test_documents_read_rejects_bad_model_without_acquiring(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service):
            events.append(("acquire", service))

        async def release(self, service):
            events.append(("release", service))

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    response = client.post(
        "/v1/documents/read",
        data={"model": "not-ocr"},
        files={"file": ("test.png", b"abc", "image/png")},
    )

    assert response.status_code == 400
    assert events == []


def test_documents_read_rejects_unsupported_file_without_acquiring(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service):
            events.append(("acquire", service))

        async def release(self, service):
            events.append(("release", service))

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    response = client.post(
        "/v1/documents/read",
        data={"model": "paddleocr-vl-1.6"},
        files={"file": ("test.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 400
    assert events == []


def test_documents_read_backend_failure_releases(monkeypatch):
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
        "/v1/documents/read",
        data={"model": "paddleocr-vl-1.6"},
        files={"file": ("test.png", b"abc", "image/png")},
    )

    assert response.status_code == 502
    assert events == [
        ("acquire", "ocr"),
        ("post", "http://ai-ocr-api:8080/layout-parsing"),
        ("release", "ocr"),
    ]
