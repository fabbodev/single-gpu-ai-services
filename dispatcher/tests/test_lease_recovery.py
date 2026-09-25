import threading
import time
import uuid

import pytest

from dispatcher import GPUDispatcher
from engine_manager import EngineCleanupError


def eventually(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.005)
    raise AssertionError("condition did not become true")


class FakeEngineManager:
    SERVICES = {"llm": (), "ocr": ()}

    def __init__(self):
        self.events = []
        self.running = set()
        self.reconcile_gate = threading.Event()
        self.reconcile_gate.set()
        self.start_gates = {}
        self.fail_reconcile = False
        self.fail_stop = False
        self.fail_start_cleanup = False
    def has_service(self, service):
        return service in self.SERVICES

    def reconcile(self, timeout):
        self.events.append(("reconcile", timeout))
        self.reconcile_gate.wait(timeout=1)
        if self.fail_reconcile:
            raise RuntimeError("reconcile failed")

    def start(self, service, timeout):
        self.events.append(("start", service, timeout))
        if self.fail_start_cleanup:
            raise EngineCleanupError("startup cleanup uncertain")
        gate = self.start_gates.get(service)
        if gate is not None:
            gate.wait(timeout=1)
        self.running.add(service)

    def stop(self, service, timeout):
        self.events.append(("stop", service, timeout))
        if self.fail_stop:
            raise RuntimeError("stop failed")
        self.running.discard(service)


@pytest.fixture
def manager():
    return FakeEngineManager()


def make_dispatcher(manager, **overrides):
    config = dict(
        max_queue_wait=0.08,
        startup_timeout=0.20,
        active_timeout=0.20,
        cleanup_timeout=0.20,
        terminal_retention=1.0,
        max_records=32,
    )
    config.update(overrides)
    dispatcher = GPUDispatcher(manager, **config)
    eventually(lambda: dispatcher.ready()["ready"])
    return dispatcher


def lease_state(dispatcher, request_id):
    return dispatcher.get_lease(request_id, dispatcher.epoch)["state"]


def test_duplicate_submit_is_idempotent_and_starts_once(manager):
    dispatcher = make_dispatcher(manager)
    request_id = str(uuid.uuid4())
    try:
        first = dispatcher.submit("llm", request_id, dispatcher.epoch, wait_timeout=0.05)
        second = dispatcher.submit("llm", request_id, dispatcher.epoch, wait_timeout=0.05)
        assert first["request_id"] == second["request_id"]

        eventually(lambda: lease_state(dispatcher, request_id) == "active")
        starts = [event for event in manager.events if event[:2] == ("start", "llm")]
        assert len(starts) == 1

        dispatcher.release("llm", request_id, dispatcher.epoch)
        eventually(lambda: lease_state(dispatcher, request_id) == "released")
    finally:
        dispatcher.close()
def test_old_release_cannot_stop_new_owner_of_same_service(manager):
    dispatcher = make_dispatcher(manager)
    first = str(uuid.uuid4())
    second = str(uuid.uuid4())
    try:
        dispatcher.submit("llm", first, dispatcher.epoch, wait_timeout=0.05)
        eventually(lambda: lease_state(dispatcher, first) == "active")
        dispatcher.release("llm", first, dispatcher.epoch)
        eventually(lambda: lease_state(dispatcher, first) == "released")

        dispatcher.submit("llm", second, dispatcher.epoch, wait_timeout=0.05)
        eventually(lambda: lease_state(dispatcher, second) == "active")
        dispatcher.release("llm", first, dispatcher.epoch)
        time.sleep(0.03)

        assert lease_state(dispatcher, second) == "active"
        assert len([e for e in manager.events if e[:2] == ("stop", "llm")]) == 1
        dispatcher.release("llm", second, dispatcher.epoch)
        eventually(lambda: lease_state(dispatcher, second) == "released")
    finally:
        dispatcher.close()


def test_queued_request_expires_without_starting(manager):
    dispatcher = make_dispatcher(manager)
    owner = str(uuid.uuid4())
    waiting = str(uuid.uuid4())
    try:
        dispatcher.submit("llm", owner, dispatcher.epoch, wait_timeout=0.05)
        eventually(lambda: lease_state(dispatcher, owner) == "active")
        dispatcher.submit("ocr", waiting, dispatcher.epoch, wait_timeout=0.03)

        eventually(lambda: lease_state(dispatcher, waiting) == "expired")
        assert not any(event[:2] == ("start", "ocr") for event in manager.events)
        dispatcher.release("llm", owner, dispatcher.epoch)
        eventually(lambda: lease_state(dispatcher, owner) == "released")
    finally:
        dispatcher.close()


def test_cancelled_queued_request_never_starts_later(manager):
    dispatcher = make_dispatcher(manager)
    owner = str(uuid.uuid4())
    waiting = str(uuid.uuid4())
    try:
        dispatcher.submit("llm", owner, dispatcher.epoch, wait_timeout=0.05)
        eventually(lambda: lease_state(dispatcher, owner) == "active")
        dispatcher.submit("ocr", waiting, dispatcher.epoch, wait_timeout=0.06)
        dispatcher.cancel("ocr", waiting, dispatcher.epoch)
        eventually(lambda: lease_state(dispatcher, waiting) == "cancelled")

        dispatcher.release("llm", owner, dispatcher.epoch)
        eventually(lambda: lease_state(dispatcher, owner) == "released")
        time.sleep(0.03)
        assert not any(event[:2] == ("start", "ocr") for event in manager.events)
    finally:
        dispatcher.close()


def test_active_lease_expires_and_is_stopped(manager):
    dispatcher = make_dispatcher(manager, active_timeout=0.05)
    request_id = str(uuid.uuid4())
    try:
        dispatcher.submit("llm", request_id, dispatcher.epoch, wait_timeout=0.03)
        eventually(lambda: lease_state(dispatcher, request_id) == "active")
        eventually(lambda: lease_state(dispatcher, request_id) == "expired")
        assert any(event[:2] == ("stop", "llm") for event in manager.events)
        assert "llm" not in manager.running
    finally:
        dispatcher.close()


def test_dispatcher_is_not_ready_until_reconciliation_completes(manager):
    manager.reconcile_gate.clear()
    dispatcher = GPUDispatcher(
        manager,
        max_queue_wait=0.05,
        startup_timeout=0.10,
        active_timeout=0.10,
        cleanup_timeout=0.10,
    )
    try:
        assert dispatcher.ready()["ready"] is False
        manager.reconcile_gate.set()
        eventually(lambda: dispatcher.ready()["ready"])
    finally:
        dispatcher.close()
def test_reconcile_failure_degrades_and_rejects_new_work(manager):
    manager.fail_reconcile = True
    dispatcher = GPUDispatcher(
        manager,
        max_queue_wait=0.05,
        startup_timeout=0.10,
        active_timeout=0.10,
        cleanup_timeout=0.10,
    )
    try:
        eventually(lambda: dispatcher.ready()["state"] == "degraded")
        with pytest.raises(RuntimeError):
            dispatcher.submit(
                "llm",
                str(uuid.uuid4()),
                dispatcher.epoch,
                wait_timeout=0.03,
            )
    finally:
        dispatcher.close()


def test_failed_stop_degrades_and_does_not_start_next_engine(manager):
    dispatcher = make_dispatcher(manager)
    owner = str(uuid.uuid4())
    waiting = str(uuid.uuid4())
    try:
        dispatcher.submit("llm", owner, dispatcher.epoch, wait_timeout=0.05)
        eventually(lambda: lease_state(dispatcher, owner) == "active")
        dispatcher.submit("ocr", waiting, dispatcher.epoch, wait_timeout=0.06)
        manager.fail_stop = True
        dispatcher.release("llm", owner, dispatcher.epoch)

        eventually(lambda: dispatcher.ready()["state"] == "degraded")
        assert not any(event[:2] == ("start", "ocr") for event in manager.events)
        assert lease_state(dispatcher, waiting) in {"queued", "expired"}
    finally:
        manager.fail_stop = False
        dispatcher.close()


def test_cancel_during_start_cleans_up_before_next_owner(manager):
    gate = threading.Event()
    manager.start_gates["llm"] = gate
    dispatcher = make_dispatcher(manager, startup_timeout=0.30)
    first = str(uuid.uuid4())
    second = str(uuid.uuid4())
    try:
        dispatcher.submit("llm", first, dispatcher.epoch, wait_timeout=0.05)
        eventually(lambda: lease_state(dispatcher, first) == "starting")
        dispatcher.cancel("llm", first, dispatcher.epoch)
        dispatcher.submit("ocr", second, dispatcher.epoch, wait_timeout=0.08)
        gate.set()

        eventually(lambda: lease_state(dispatcher, first) == "cancelled")
        eventually(lambda: lease_state(dispatcher, second) == "active")
        starts = [event[1] for event in manager.events if event[0] == "start"]
        stops = [event[1] for event in manager.events if event[0] == "stop"]
        assert starts[:2] == ["llm", "ocr"]
        assert stops[0] == "llm"
        dispatcher.release("ocr", second, dispatcher.epoch)
        eventually(lambda: lease_state(dispatcher, second) == "released")
    finally:
        dispatcher.close()


def test_uncertain_start_cleanup_degrades_and_blocks_following_work(manager):
    dispatcher = make_dispatcher(manager)
    first = str(uuid.uuid4())
    second = str(uuid.uuid4())
    try:
        manager.fail_start_cleanup = True
        dispatcher.submit("llm", first, dispatcher.epoch, wait_timeout=0.05)
        eventually(lambda: dispatcher.ready()["state"] == "degraded")
        assert lease_state(dispatcher, first) == "failed"

        with pytest.raises(RuntimeError):
            dispatcher.submit("ocr", second, dispatcher.epoch, wait_timeout=0.05)
        assert not any(event[:2] == ("start", "ocr") for event in manager.events)
    finally:
        dispatcher.close()


def test_cancel_before_submit_creates_tombstone_and_blocks_late_admission(manager):
    dispatcher = make_dispatcher(manager)
    request_id = str(uuid.uuid4())
    try:
        result = dispatcher.cancel("llm", request_id, dispatcher.epoch)
        assert result["state"] == "cancelled"

        replay = dispatcher.submit(
            "llm",
            request_id,
            dispatcher.epoch,
            wait_timeout=0.05,
        )
        assert replay["state"] == "cancelled"
        time.sleep(0.03)
        assert not any(event[:2] == ("start", "llm") for event in manager.events)
    finally:
        dispatcher.close()
