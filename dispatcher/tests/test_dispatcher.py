import threading
import time

import pytest

from dispatcher import GPUDispatcher


class FakeEngineManager:
    def __init__(self, fail_on_start=None):
        self.started = []
        self.stopped = []
        self.fail_on_start = fail_on_start

    def start(self, service):
        self.started.append(service)
        if service == self.fail_on_start:
            raise RuntimeError("start failed")

    def stop(self, service):
        self.stopped.append(service)


def test_acquire_starts_engine_and_sets_owner():
    manager = FakeEngineManager()
    dispatcher = GPUDispatcher(manager)

    dispatcher.acquire("llm")

    assert manager.started == ["llm"]
    assert dispatcher.current_service == "llm"


def test_release_stops_engine_and_clears_owner():
    manager = FakeEngineManager()
    dispatcher = GPUDispatcher(manager)
    dispatcher.acquire("llm")

    dispatcher.release("llm")

    assert manager.stopped == ["llm"]
    assert dispatcher.current_service is None


def test_release_rejects_non_owner():
    manager = FakeEngineManager()
    dispatcher = GPUDispatcher(manager)
    dispatcher.acquire("ocr")

    with pytest.raises(RuntimeError, match="GPU is owned by ocr"):
        dispatcher.release("llm")


def test_failed_start_does_not_assign_gpu_owner():
    manager = FakeEngineManager(fail_on_start="llm")
    dispatcher = GPUDispatcher(manager)

    with pytest.raises(RuntimeError, match="start failed"):
        dispatcher.acquire("llm")

    assert dispatcher.current_service is None


def test_competing_acquire_waits_until_current_service_releases():
    manager = FakeEngineManager()
    dispatcher = GPUDispatcher(manager)
    dispatcher.acquire("ocr")

    acquired = threading.Event()

    def acquire_llm():
        dispatcher.acquire("llm")
        acquired.set()

    thread = threading.Thread(target=acquire_llm)
    thread.start()

    time.sleep(0.05)
    assert not acquired.is_set()
    assert dispatcher.current_service == "ocr"
    assert manager.started == ["ocr"]

    dispatcher.release("ocr")

    assert acquired.wait(timeout=1.0)
    thread.join(timeout=1.0)
    assert dispatcher.current_service == "llm"
    assert manager.started == ["ocr", "llm"]

    dispatcher.release("llm")
