import asyncio
import os
from pathlib import Path
from dataclasses import dataclass
import uuid

import httpx


DISPATCHER_PROTOCOL_VERSION = 2
DEFAULT_TOKEN_FILE = "/run/secrets/dispatcher-token"
TERMINAL_STATES = {"released", "cancelled", "expired", "failed"}


class DispatcherAcquireError(RuntimeError):
    pass


@dataclass(frozen=True)
class LeaseHandle:
    request_id: str
    service: str
    epoch: str


class DispatcherClient:
    def __init__(
        self,
        base_url: str,
        *,
        request_timeout=10.0,
        queue_wait=30.0,
        startup_timeout=120.0,
        poll_interval=0.2,
        transport=None,
        request_id_factory=None,
        internal_token=None,
        token_file=None,
    ):
        self.base_url = base_url.rstrip("/")
        self.request_timeout = float(request_timeout)
        self.queue_wait = float(queue_wait)
        self.startup_timeout = float(startup_timeout)
        self.poll_interval = float(poll_interval)
        self.transport = transport
        self.request_id_factory = request_id_factory or (
            lambda: str(uuid.uuid4())
        )
        if internal_token is None:
            token_path = token_file or os.getenv(
                "AI_DISPATCHER_TOKEN_FILE",
                DEFAULT_TOKEN_FILE,
            )
            internal_token = Path(token_path).read_text().strip()
        if len(internal_token) < 32:
            raise ValueError("dispatcher internal token is too short")
        self.internal_token = internal_token

    @staticmethod
    def lease_handle(*, request_id, service, epoch):
        return LeaseHandle(
            request_id=request_id,
            service=service,
            epoch=epoch,
        )

    def _client(self):
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.request_timeout,
            transport=self.transport,
            headers={
                "X-AI-Internal-Token": self.internal_token,
            },
        )

    async def ready(self):
        async with self._client() as client:
            response = await client.get("/ready")
            response.raise_for_status()
            body = response.json()
            if body.get("protocol") != DISPATCHER_PROTOCOL_VERSION:
                raise DispatcherAcquireError(
                    "incompatible dispatcher protocol: "
                    f"expected {DISPATCHER_PROTOCOL_VERSION}, "
                    f"got {body.get('protocol')}"
                )
            return body

    async def acquire(self, service: str):
        request_id = self.request_id_factory()
        lease = None
        attempted = False

        async with self._client() as client:
            ready_response = await client.get("/ready")
            ready_response.raise_for_status()
            ready = ready_response.json()
            if ready.get("protocol") != DISPATCHER_PROTOCOL_VERSION:
                raise DispatcherAcquireError(
                    "incompatible dispatcher protocol: "
                    f"expected {DISPATCHER_PROTOCOL_VERSION}, "
                    f"got {ready.get('protocol')}"
                )
            if not ready.get("ready"):
                raise DispatcherAcquireError(
                    f"dispatcher not ready: {ready.get('reason') or ready.get('state')}"
                )
            epoch = ready["epoch"]
            lease = LeaseHandle(
                request_id=request_id,
                service=service,
                epoch=epoch,
            )

            try:
                attempted = True
                response = await client.post(
                    f"/acquire/{service}",
                    json={
                        "request_id": request_id,
                        "epoch": epoch,
                        "wait_timeout": self.queue_wait,
                    },
                )
                response.raise_for_status()
                state = response.json().get("state")
                if state == "active":
                    return lease
                if state in TERMINAL_STATES:
                    raise DispatcherAcquireError(
                        f"dispatcher acquisition ended in state {state}"
                    )

                loop = asyncio.get_running_loop()
                deadline = (
                    loop.time()
                    + self.queue_wait
                    + self.startup_timeout
                    + 5.0
                )
                while True:
                    if loop.time() >= deadline:
                        raise DispatcherAcquireError(
                            "timed out waiting for dispatcher acquisition"
                        )
                    response = await client.get(
                        f"/leases/{request_id}",
                        params={"epoch": epoch},
                    )
                    response.raise_for_status()
                    body = response.json()
                    state = body.get("state")
                    if state == "active":
                        return lease
                    if state in TERMINAL_STATES:
                        detail = body.get("error")
                        suffix = f": {detail}" if detail else ""
                        raise DispatcherAcquireError(
                            f"dispatcher acquisition ended in state {state}{suffix}"
                        )
                    await asyncio.sleep(self.poll_interval)
            except BaseException:
                if attempted and lease is not None:
                    await asyncio.shield(
                        self._best_effort_cancel(client, lease)
                    )
                raise
    async def release(self, lease: LeaseHandle):
        async with self._client() as client:
            response = await client.post(
                f"/release/{lease.service}",
                json={
                    "request_id": lease.request_id,
                    "epoch": lease.epoch,
                },
            )
            response.raise_for_status()
            return response.json()

    async def cancel(self, lease: LeaseHandle):
        async with self._client() as client:
            response = await client.post(
                f"/cancel/{lease.service}",
                json={
                    "request_id": lease.request_id,
                    "epoch": lease.epoch,
                },
            )
            response.raise_for_status()
            return response.json()

    async def _best_effort_cancel(self, client, lease):
        try:
            response = await client.post(
                f"/cancel/{lease.service}",
                json={
                    "request_id": lease.request_id,
                    "epoch": lease.epoch,
                },
            )
            response.raise_for_status()
        except Exception:
            return
