import threading
import time

import pytest

from dispatcher import GPUDispatcher


class FakeEngineManager:
    def __init__(self):
        self.events = []

    def start(self, service):
        self.events.append(("start", service))

    def stop(self, service):
        self.events.append(("stop", service))


def test_acquire_starts_engine_and_records_owner():
    manager = FakeEngineManager()
    dispatcher = GPUDispatcher(manager)

    dispatcher.acquire("llm")

    assert dispatcher.current_service == "llm"
    assert manager.events == [("start", "llm")]


def test_release_stops_engine_and_clears_owner():
    manager = FakeEngineManager()
    dispatcher = GPUDispatcher(manager)
    dispatcher.acquire("embeddings")

    dispatcher.release("embeddings")

    assert dispatcher.current_service is None
    assert manager.events == [
        ("start", "embeddings"),
        ("stop", "embeddings"),
    ]


def test_release_rejects_non_owner():
    dispatcher = GPUDispatcher(FakeEngineManager())
    dispatcher.acquire("llm")

    with pytest.raises(RuntimeError):
        dispatcher.release("stt")


def test_competing_acquire_waits_until_release():
    manager = FakeEngineManager()
    dispatcher = GPUDispatcher(manager)
    dispatcher.acquire("ocr")

    acquired = threading.Event()

    def request_llm():
        dispatcher.acquire("llm")
        acquired.set()

    thread = threading.Thread(target=request_llm)
    thread.start()

    time.sleep(0.05)
    assert not acquired.is_set()
    assert dispatcher.current_service == "ocr"

    dispatcher.release("ocr")
    assert acquired.wait(timeout=1.0)
    assert dispatcher.current_service == "llm"

    dispatcher.release("llm")
    thread.join(timeout=1.0)

    assert manager.events == [
        ("start", "ocr"),
        ("stop", "ocr"),
        ("start", "llm"),
        ("stop", "llm"),
    ]
