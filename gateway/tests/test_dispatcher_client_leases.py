import json

import httpx
import pytest

from app.dispatcher_client import DispatcherClient


@pytest.mark.asyncio
async def test_acquire_polls_brief_dispatcher_protocol_until_active():
    calls = []
    lease_polls = 0

    async def handler(request):
        nonlocal lease_polls
        calls.append((request.method, request.url.path))
        if request.url.path == "/ready":
            return httpx.Response(
                200,
                json={"ready": True, "state": "idle", "epoch": "epoch-1", "protocol": 2},
            )
        if request.url.path == "/acquire/llm":
            body = json.loads(request.content)
            assert body == {
                "request_id": "req-1",
                "epoch": "epoch-1",
                "wait_timeout": 30.0,
            }
            return httpx.Response(
                202,
                json={"request_id": "req-1", "service": "llm", "state": "queued"},
            )
        if request.url.path == "/leases/req-1":
            assert request.url.params["epoch"] == "epoch-1"
            lease_polls += 1
            state = "queued" if lease_polls == 1 else "active"
            return httpx.Response(
                200,
                json={"request_id": "req-1", "service": "llm", "state": state},
            )
        raise AssertionError(request.url)

    client = DispatcherClient(
        "http://dispatcher.test",
        transport=httpx.MockTransport(handler),
        request_id_factory=lambda: "req-1",
        poll_interval=0,
        queue_wait=30,
        startup_timeout=120,
    )

    lease = await client.acquire("llm")

    assert lease.request_id == "req-1"
    assert lease.epoch == "epoch-1"
    assert lease.service == "llm"
    assert calls == [
        ("GET", "/ready"),
        ("POST", "/acquire/llm"),
        ("GET", "/leases/req-1"),
        ("GET", "/leases/req-1"),
    ]
@pytest.mark.asyncio
async def test_lost_acquire_response_triggers_cancel_with_same_identity():
    calls = []

    async def handler(request):
        calls.append((request.method, request.url.path, request.content))
        if request.url.path == "/ready":
            return httpx.Response(
                200,
                json={"ready": True, "state": "idle", "epoch": "epoch-1", "protocol": 2},
            )
        if request.url.path == "/acquire/llm":
            raise httpx.ReadTimeout("lost response", request=request)
        if request.url.path == "/cancel/llm":
            body = json.loads(request.content)
            assert body == {"request_id": "req-1", "epoch": "epoch-1"}
            return httpx.Response(
                200,
                json={"request_id": "req-1", "service": "llm", "state": "cancelled"},
            )
        raise AssertionError(request.url)

    client = DispatcherClient(
        "http://dispatcher.test",
        transport=httpx.MockTransport(handler),
        request_id_factory=lambda: "req-1",
        poll_interval=0,
    )

    with pytest.raises(httpx.ReadTimeout):
        await client.acquire("llm")

    assert [path for _, path, _ in calls] == [
        "/ready",
        "/acquire/llm",
        "/cancel/llm",
    ]


@pytest.mark.asyncio
async def test_release_uses_lease_identity_not_just_service():
    seen = {}

    async def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"request_id": "req-1", "service": "llm", "state": "released"},
        )

    client = DispatcherClient(
        "http://dispatcher.test",
        transport=httpx.MockTransport(handler),
    )
    lease = client.lease_handle(
        request_id="req-1",
        service="llm",
        epoch="epoch-1",
    )

    await client.release(lease)

    assert seen == {
        "path": "/release/llm",
        "body": {"request_id": "req-1", "epoch": "epoch-1"},
    }


@pytest.mark.asyncio
async def test_terminal_lease_state_fails_acquire_instead_of_waiting_forever():
    async def handler(request):
        if request.url.path == "/ready":
            return httpx.Response(
                200,
                json={"ready": True, "state": "idle", "epoch": "epoch-1", "protocol": 2},
            )
        if request.url.path == "/acquire/llm":
            return httpx.Response(
                202,
                json={"request_id": "req-1", "service": "llm", "state": "queued"},
            )
        if request.url.path == "/leases/req-1":
            return httpx.Response(
                200,
                json={
                    "request_id": "req-1",
                    "service": "llm",
                    "state": "expired",
                    "error": None,
                },
            )
        if request.url.path == "/cancel/llm":
            return httpx.Response(200, json={"state": "expired"})
        raise AssertionError(request.url)

    client = DispatcherClient(
        "http://dispatcher.test",
        transport=httpx.MockTransport(handler),
        request_id_factory=lambda: "req-1",
        poll_interval=0,
    )

    with pytest.raises(RuntimeError, match="expired"):
        await client.acquire("llm")


@pytest.mark.asyncio
async def test_acquire_rejects_incompatible_dispatcher_protocol_before_submit():
    calls = []

    async def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/ready":
            return httpx.Response(
                200,
                json={
                    "ready": True,
                    "state": "idle",
                    "epoch": "epoch-1",
                    "protocol": 1,
                },
            )
        raise AssertionError("acquire must not be sent to incompatible protocol")

    client = DispatcherClient(
        "http://dispatcher.test",
        transport=httpx.MockTransport(handler),
        request_id_factory=lambda: "req-1",
        poll_interval=0,
    )

    with pytest.raises(RuntimeError, match="protocol"):
        await client.acquire("llm")

    assert calls == ["/ready"]
