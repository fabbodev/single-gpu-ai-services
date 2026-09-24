import pytest

from engine_manager import EngineManager


class FakeRunner:
    def __init__(self, running=None, fail_health_for=None):
        self.running = set(running or [])
        self.fail_health_for = set(fail_health_for or [])
        self.events = []

    def run(self, *command, timeout=None):
        self.events.append(command)

        if command[:3] == ("docker", "inspect", "-f"):
            container = command[-1]
            if container in self.running:
                return "true\n"
            return "false\n"

        if command[:2] == ("docker", "start"):
            self.running.add(command[2])
            return ""

        if command[:2] == ("docker", "stop"):
            self.running.discard(command[2])
            return ""

        if command[:2] == ("curl", "-fsS"):
            url = command[-1]
            if url in self.fail_health_for:
                raise RuntimeError("health failed")
            return "ok"

        raise AssertionError(f"Unexpected command: {command}")


def test_single_component_service_starts_and_health_checks():
    runner = FakeRunner()
    manager = EngineManager(runner, health_attempts=1, health_interval=0)

    manager.start("llm", timeout=0.2)

    assert "ai-llm" in runner.running
    assert ("docker", "start", "ai-llm") in runner.events
    assert any(
        event[:2] == ("curl", "-fsS")
        and event[-1] == "http://ai-llm:8080/health"
        for event in runner.events
    )


def test_running_component_is_not_started_twice():
    runner = FakeRunner(running={"ai-llm"})
    manager = EngineManager(runner, health_attempts=1, health_interval=0)

    manager.start("llm", timeout=0.2)

    assert ("docker", "start", "ai-llm") not in runner.events


def test_unknown_service_is_rejected():
    manager = EngineManager(FakeRunner(), health_attempts=1, health_interval=0)

    with pytest.raises(ValueError):
        manager.start("does-not-exist", timeout=0.2)


def test_ocr_starts_vlm_before_api():
    runner = FakeRunner()
    manager = EngineManager(runner, health_attempts=1, health_interval=0)

    manager.start("ocr", timeout=0.2)

    starts = [event for event in runner.events if event[:2] == ("docker", "start")]
    assert starts == [
        ("docker", "start", "ai-ocr-vlm"),
        ("docker", "start", "ai-ocr-api"),
    ]


def test_ocr_stops_in_reverse_order():
    runner = FakeRunner(running={"ai-ocr-vlm", "ai-ocr-api"})
    manager = EngineManager(runner, health_attempts=1, health_interval=0)

    manager.stop("ocr", timeout=0.2)

    stops = [event for event in runner.events if event[:2] == ("docker", "stop")]
    assert stops == [
        ("docker", "stop", "ai-ocr-api"),
        ("docker", "stop", "ai-ocr-vlm"),
    ]


def test_partial_ocr_start_failure_rolls_back():
    api_health = "http://ai-ocr-api:8080/health"
    runner = FakeRunner(fail_health_for={api_health})
    manager = EngineManager(runner, health_attempts=1, health_interval=0)

    with pytest.raises(RuntimeError):
        manager.start("ocr", timeout=0.2)

    assert "ai-ocr-vlm" not in runner.running
    assert "ai-ocr-api" not in runner.running
    stops = [event for event in runner.events if event[:2] == ("docker", "stop")]
    assert stops[-2:] == [
        ("docker", "stop", "ai-ocr-api"),
        ("docker", "stop", "ai-ocr-vlm"),
    ]
