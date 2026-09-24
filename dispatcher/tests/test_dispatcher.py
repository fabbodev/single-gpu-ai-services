import time
import uuid

import pytest

from dispatcher import GPUDispatcher, LeaseConflict


class FakeEngineManager:
    SERVICES = {"llm": (), "embeddings": (), "ocr": ()}

    def __init__(self):
        self.events = []

    def has_service(self, service):
        return service in self.SERVICES

    def reconcile(self, timeout):
        self.events.append(("reconcile", timeout))

    def start(self, service, timeout):
        self.events.append(("start", service))

    def stop(self, service, timeout):
        self.events.append(("stop", service))


def eventually(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition did not become true")


def make_dispatcher(manager):
    dispatcher = GPUDispatcher(
        manager,
        max_queue_wait=0.1,
        startup_timeout=0.1,
        active_timeout=0.3,
        cleanup_timeout=0.1,
    )
    eventually(lambda: dispatcher.ready()["ready"])
    return dispatcher


def test_submit_starts_engine_and_records_active_lease():
    manager = FakeEngineManager()
    dispatcher = make_dispatcher(manager)
    request_id = str(uuid.uuid4())
    try:
        dispatcher.submit("llm", request_id, dispatcher.epoch, wait_timeout=0.05)
        eventually(
            lambda: dispatcher.get_lease(request_id, dispatcher.epoch)["state"]
            == "active"
        )
        assert ("start", "llm") in manager.events
    finally:
        dispatcher.close()


def test_release_stops_engine_and_marks_lease_released():
    manager = FakeEngineManager()
    dispatcher = make_dispatcher(manager)
    request_id = str(uuid.uuid4())
    try:
        dispatcher.submit(
            "embeddings", request_id, dispatcher.epoch, wait_timeout=0.05
        )
        eventually(
            lambda: dispatcher.get_lease(request_id, dispatcher.epoch)["state"]
            == "active"
        )
        dispatcher.release("embeddings", request_id, dispatcher.epoch)
        eventually(
            lambda: dispatcher.get_lease(request_id, dispatcher.epoch)["state"]
            == "released"
        )
        assert ("stop", "embeddings") in manager.events
    finally:
        dispatcher.close()


def test_release_rejects_wrong_service_for_request_identity():
    manager = FakeEngineManager()
    dispatcher = make_dispatcher(manager)
    request_id = str(uuid.uuid4())
    try:
        dispatcher.submit("llm", request_id, dispatcher.epoch, wait_timeout=0.05)
        eventually(
            lambda: dispatcher.get_lease(request_id, dispatcher.epoch)["state"]
            == "active"
        )
        with pytest.raises(LeaseConflict):
            dispatcher.release("ocr", request_id, dispatcher.epoch)
    finally:
        dispatcher.close()


def test_competing_submit_waits_until_current_lease_releases():
    manager = FakeEngineManager()
    dispatcher = make_dispatcher(manager)
    first = str(uuid.uuid4())
    second = str(uuid.uuid4())
    try:
        dispatcher.submit("ocr", first, dispatcher.epoch, wait_timeout=0.08)
        eventually(
            lambda: dispatcher.get_lease(first, dispatcher.epoch)["state"]
            == "active"
        )
        dispatcher.submit("llm", second, dispatcher.epoch, wait_timeout=0.08)
        assert dispatcher.get_lease(second, dispatcher.epoch)["state"] == "queued"

        dispatcher.release("ocr", first, dispatcher.epoch)
        eventually(
            lambda: dispatcher.get_lease(second, dispatcher.epoch)["state"]
            == "active"
        )
        assert ("stop", "ocr") in manager.events
        assert ("start", "llm") in manager.events
    finally:
        dispatcher.close()
