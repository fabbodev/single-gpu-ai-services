from collections import deque
from dataclasses import dataclass
import threading
import time
import uuid

from engine_manager import EngineCleanupError


DISPATCHER_PROTOCOL_VERSION = 2
TERMINAL_STATES = {"released", "cancelled", "expired", "failed"}


class DispatcherError(RuntimeError):
    pass


class DispatcherNotReady(DispatcherError):
    pass


class LeaseConflict(DispatcherError):
    pass


class LeaseNotFound(DispatcherError):
    pass


class StaleEpoch(DispatcherError):
    pass


@dataclass
class LeaseRecord:
    request_id: str
    service: str
    wait_timeout: float
    created_at: float
    queue_deadline: float
    state: str = "queued"
    cancel_requested: bool = False
    terminal_target: str | None = None
    active_deadline: float | None = None
    terminal_at: float | None = None
    error: str | None = None


class GPUDispatcher:
    def __init__(
        self,
        engine_manager,
        *,
        max_queue_wait=30.0,
        startup_timeout=120.0,
        active_timeout=330.0,
        cleanup_timeout=60.0,
        terminal_retention=600.0,
        max_records=4096,
        clock=time.monotonic,
    ):
        self._engine_manager = engine_manager
        self.max_queue_wait = float(max_queue_wait)
        self.startup_timeout = float(startup_timeout)
        self.active_timeout = float(active_timeout)
        self.cleanup_timeout = float(cleanup_timeout)
        self.terminal_retention = float(terminal_retention)
        self.max_records = int(max_records)
        self._clock = clock

        for name, value in (
            ("max_queue_wait", self.max_queue_wait),
            ("startup_timeout", self.startup_timeout),
            ("active_timeout", self.active_timeout),
            ("cleanup_timeout", self.cleanup_timeout),
            ("terminal_retention", self.terminal_retention),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.max_records <= 0:
            raise ValueError("max_records must be positive")

        self.epoch = str(uuid.uuid4())
        self._condition = threading.Condition()
        self._records: dict[str, LeaseRecord] = {}
        self._queue = deque()
        self._current_request_id: str | None = None
        self._system_state = "reconciling"
        self._degraded_reason: str | None = None
        self._closed = False
        self._worker = threading.Thread(
            target=self._run,
            name="gpu-dispatcher-worker",
            daemon=True,
        )
        self._worker.start()

    def ready(self):
        with self._condition:
            if self._system_state == "ready":
                state = "busy" if self._current_request_id else "idle"
                return {
                    "ready": True,
                    "state": state,
                    "epoch": self.epoch,
                    "protocol": DISPATCHER_PROTOCOL_VERSION,
                    "reason": None,
                }
            return {
                "ready": False,
                "state": self._system_state,
                "epoch": self.epoch,
                "protocol": DISPATCHER_PROTOCOL_VERSION,
                "reason": self._degraded_reason,
            }

    def submit(self, service, request_id, epoch, *, wait_timeout=30.0):
        with self._condition:
            self._validate_epoch(epoch)
            self._require_ready()
            if not self._engine_manager.has_service(service):
                raise ValueError(f"Unknown service: {service}")

            wait_timeout = float(wait_timeout)
            if wait_timeout <= 0 or wait_timeout > self.max_queue_wait:
                raise ValueError(
                    f"wait_timeout must be > 0 and <= {self.max_queue_wait}"
                )

            existing = self._records.get(request_id)
            if existing is not None:
                if existing.service != service:
                    raise LeaseConflict(
                        f"request_id {request_id} was already admitted "
                        "for a different service"
                    )
                if existing.state in TERMINAL_STATES:
                    return self._snapshot(existing)
                if existing.wait_timeout != wait_timeout:
                    raise LeaseConflict(
                        f"request_id {request_id} was already admitted "
                        "with different parameters"
                    )
                return self._snapshot(existing)

            self._prune_terminal_locked()
            if len(self._records) >= self.max_records:
                raise DispatcherNotReady("lease registry is full")

            now = self._clock()
            record = LeaseRecord(
                request_id=request_id,
                service=service,
                wait_timeout=wait_timeout,
                created_at=now,
                queue_deadline=now + wait_timeout,
            )
            self._records[request_id] = record
            self._queue.append(request_id)
            self._condition.notify_all()
            return self._snapshot(record)

    def get_lease(self, request_id, epoch):
        with self._condition:
            self._validate_epoch(epoch)
            record = self._records.get(request_id)
            if record is None:
                raise LeaseNotFound(request_id)
            return self._snapshot(record)

    def release(self, service, request_id, epoch):
        return self._request_stop(
            service,
            request_id,
            epoch,
            terminal_target="released",
        )

    def cancel(self, service, request_id, epoch):
        return self._request_stop(
            service,
            request_id,
            epoch,
            terminal_target="cancelled",
        )

    def close(self, timeout=1.0):
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        self._worker.join(timeout=timeout)
    def _request_stop(self, service, request_id, epoch, *, terminal_target):
        with self._condition:
            self._validate_epoch(epoch)
            record = self._records.get(request_id)
            if record is None:
                if terminal_target != "cancelled":
                    raise LeaseNotFound(request_id)
                if not self._engine_manager.has_service(service):
                    raise ValueError(f"Unknown service: {service}")
                self._prune_terminal_locked()
                if len(self._records) >= self.max_records:
                    raise DispatcherNotReady("lease registry is full")
                now = self._clock()
                record = LeaseRecord(
                    request_id=request_id,
                    service=service,
                    wait_timeout=0.0,
                    created_at=now,
                    queue_deadline=now,
                    state="cancelled",
                    terminal_at=now,
                )
                self._records[request_id] = record
                return self._snapshot(record)
            if record.service != service:
                raise LeaseConflict(
                    f"request_id {request_id} belongs to {record.service}"
                )
            if record.state in TERMINAL_STATES:
                return self._snapshot(record)

            if record.state == "queued":
                self._mark_terminal_locked(record, terminal_target)
            elif record.state == "starting":
                record.cancel_requested = True
                record.terminal_target = terminal_target
            elif record.state == "active":
                record.state = "stopping"
                record.terminal_target = terminal_target
            elif record.state == "stopping":
                if record.terminal_target is None:
                    record.terminal_target = terminal_target
            self._condition.notify_all()
            return self._snapshot(record)

    def _run(self):
        try:
            self._engine_manager.reconcile(self.cleanup_timeout)
        except Exception as exc:
            with self._condition:
                self._system_state = "degraded"
                self._degraded_reason = f"reconciliation failed: {exc}"
                self._condition.notify_all()
            return

        with self._condition:
            self._system_state = "ready"
            self._condition.notify_all()

        while True:
            action = None
            record = None
            with self._condition:
                if self._closed:
                    return

                now = self._clock()
                self._expire_queued_locked(now)
                self._prune_terminal_locked(now)

                if self._system_state != "ready":
                    self._condition.wait(timeout=0.05)
                    continue

                if self._current_request_id is not None:
                    record = self._records[self._current_request_id]
                    if (
                        record.state == "active"
                        and record.active_deadline is not None
                        and now >= record.active_deadline
                    ):
                        record.state = "stopping"
                        record.terminal_target = "expired"
                    if record.state == "stopping":
                        action = "stop"
                else:
                    record = self._next_queued_locked(now)
                    if record is not None:
                        record.state = "starting"
                        self._current_request_id = record.request_id
                        action = "start"

                if action is None:
                    self._condition.wait(timeout=self._next_wait_locked(now))
                    continue

            if action == "start":
                self._perform_start(record)
            else:
                self._perform_stop(record)

    def _perform_start(self, record):
        try:
            self._engine_manager.start(
                record.service,
                self.startup_timeout,
            )
        except EngineCleanupError as exc:
            with self._condition:
                record.error = str(exc)
                self._mark_terminal_locked(record, "failed")
                self._system_state = "degraded"
                self._degraded_reason = (
                    f"startup cleanup uncertain for {record.request_id}: {exc}"
                )
                self._condition.notify_all()
            return
        except Exception as exc:
            with self._condition:
                record.error = str(exc)
                self._mark_terminal_locked(record, "failed")
                self._current_request_id = None
                self._condition.notify_all()
            return
        with self._condition:
            if record.cancel_requested:
                record.state = "stopping"
                if record.terminal_target is None:
                    record.terminal_target = "cancelled"
            else:
                record.state = "active"
                record.active_deadline = self._clock() + self.active_timeout
            self._condition.notify_all()

    def _perform_stop(self, record):
        try:
            self._engine_manager.stop(
                record.service,
                self.cleanup_timeout,
            )
        except Exception as exc:
            with self._condition:
                record.error = str(exc)
                self._system_state = "degraded"
                self._degraded_reason = (
                    f"cleanup failed for {record.request_id}: {exc}"
                )
                self._condition.notify_all()
            return

        with self._condition:
            target = record.terminal_target or "released"
            self._mark_terminal_locked(record, target)
            self._current_request_id = None
            self._condition.notify_all()

    def _next_queued_locked(self, now):
        while self._queue:
            request_id = self._queue.popleft()
            record = self._records.get(request_id)
            if record is None or record.state != "queued":
                continue
            if now >= record.queue_deadline:
                self._mark_terminal_locked(record, "expired")
                continue
            return record
        return None

    def _expire_queued_locked(self, now):
        for request_id in tuple(self._queue):
            record = self._records.get(request_id)
            if (
                record is not None
                and record.state == "queued"
                and now >= record.queue_deadline
            ):
                self._mark_terminal_locked(record, "expired")

    def _next_wait_locked(self, now):
        deadlines = []
        if self._current_request_id is not None:
            record = self._records[self._current_request_id]
            if record.state == "active" and record.active_deadline is not None:
                deadlines.append(record.active_deadline)
        for request_id in self._queue:
            record = self._records.get(request_id)
            if record is not None and record.state == "queued":
                deadlines.append(record.queue_deadline)
        if not deadlines:
            return 0.05
        return max(0.001, min(0.05, min(deadlines) - now))

    def _mark_terminal_locked(self, record, state):
        record.state = state
        record.terminal_at = self._clock()
        record.active_deadline = None

    def _prune_terminal_locked(self, now=None):
        now = self._clock() if now is None else now
        stale = [
            request_id
            for request_id, record in self._records.items()
            if (
                record.state in TERMINAL_STATES
                and record.terminal_at is not None
                and now - record.terminal_at >= self.terminal_retention
                and request_id != self._current_request_id
            )
        ]
        for request_id in stale:
            self._records.pop(request_id, None)

    def _require_ready(self):
        if self._system_state != "ready":
            raise DispatcherNotReady(
                self._degraded_reason or f"dispatcher is {self._system_state}"
            )

    def _validate_epoch(self, epoch):
        if epoch != self.epoch:
            raise StaleEpoch(
                f"stale dispatcher epoch {epoch}; current epoch is {self.epoch}"
            )

    @staticmethod
    def _snapshot(record):
        return {
            "request_id": record.request_id,
            "service": record.service,
            "state": record.state,
            "error": record.error,
        }
