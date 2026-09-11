import httpx
from fastapi.testclient import TestClient

from app import main
from app.main import app

client = TestClient(app)


def test_chat_completions_acquires_llm_forwards_request_and_releases(monkeypatch):
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
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Hello"},
                        "finish_reason": "stop",
                    }
                ],
            }

    class FakeHTTPClient:
        async def post(self, url, json):
            events.append(("post", url, json))
            return FakeResponse()

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    monkeypatch.setattr(main, "http_client", FakeHTTPClient())

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "qwen3-8b",
            "messages": [{"role": "user", "content": "Say hello"}],
            "temperature": 0.2,
            "max_tokens": 32,
            "top_p": 0.9,
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "Hello"
    assert events[0] == ("acquire", "llm")
    assert events[-1] == ("release", "llm")


def test_chat_completions_forwards_tool_calling_fields(monkeypatch):
    forwarded = {}

    class FakeDispatcher:
        async def acquire(self, service):
            pass

        async def release(self, service):
            pass

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"role": "assistant", "tool_calls": []}}]}

    class FakeHTTPClient:
        async def post(self, url, json):
            forwarded.update(json)
            return FakeResponse()

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())
    monkeypatch.setattr(main, "http_client", FakeHTTPClient())

    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_document",
                "description": "Read a document with OCR",
                "parameters": {
                    "type": "object",
                    "properties": {"content_base64": {"type": "string"}},
                    "required": ["content_base64"],
                },
            },
        }
    ]

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "qwen3-8b",
            "messages": [{"role": "user", "content": "Read this document"}],
            "tools": tools,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
        },
    )

    assert response.status_code == 200
    assert forwarded["tools"] == tools
    assert forwarded["tool_choice"] == "auto"
    assert forwarded["parallel_tool_calls"] is False


def test_chat_completions_rejects_unsupported_model_without_acquiring(monkeypatch):
    events = []

    class FakeDispatcher:
        async def acquire(self, service):
            events.append(("acquire", service))

        async def release(self, service):
            events.append(("release", service))

    monkeypatch.setattr(main, "dispatcher", FakeDispatcher())

    response = client.post(
        "/v1/chat/completions",
        json={"model": "not-qwen", "messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 400
    assert events == []


def test_chat_completions_backend_failure_releases_llm(monkeypatch):
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
        "/v1/chat/completions",
        json={"model": "qwen3-8b", "messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 502
    assert events == [
        ("acquire", "llm"),
        ("post", "http://ai-llm:8080/v1/chat/completions"),
        ("release", "llm"),
    ]
