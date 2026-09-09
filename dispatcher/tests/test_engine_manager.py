import pytest

from engine_manager import EngineManager


class FakeRunner:
    def __init__(self, running=None, fail_health_urls=None):
        self.running = set(running or [])
        self.fail_health_urls = set(fail_health_urls or [])
        self.commands = []

    def run(self, *command):
        self.commands.append(command)

        if command[:4] == ("docker", "inspect", "-f", "{{.State.Running}}"):
            container = command[4]
            return "true\n" if container in self.running else "false\n"

        if command[:2] == ("docker", "start"):
            self.running.add(command[2])
            return command[2] + "\n"

        if command[:2] == ("docker", "stop"):
            self.running.discard(command[2])
            return command[2] + "\n"

        if command[:2] == ("curl", "-fsS"):
            url = command[2]
            if url in self.fail_health_urls:
                raise RuntimeError(f"health failed: {url}")
            return "ok"

        raise AssertionError(f"Unexpected command: {command}")


def manager(runner):
    return EngineManager(runner=runner, health_attempts=1, health_interval=0)


def test_service_map_contains_all_public_logical_services():
    assert set(EngineManager.SERVICES) == {
        "llm",
        "stt",
        "tts",
        "embeddings",
        "reranker",
        "ocr",
    }
    assert EngineManager.SERVICES["ocr"] == [
        ("ai-ocr-vlm", "http://ai-ocr-vlm:8080/health"),
        ("ai-ocr-api", "http://ai-ocr-api:8080/health"),
    ]


def test_start_single_service_starts_then_checks_health():
    runner = FakeRunner()

    manager(runner).start("llm")

    assert runner.running == {"ai-llm"}
    assert runner.commands == [
        ("docker", "inspect", "-f", "{{.State.Running}}", "ai-llm"),
        ("docker", "start", "ai-llm"),
        ("curl", "-fsS", "http://ai-llm:8080/health"),
    ]


def test_start_does_not_restart_already_running_component():
    runner = FakeRunner(running={"ai-llm"})

    manager(runner).start("llm")

    assert ("docker", "start", "ai-llm") not in runner.commands
    assert runner.commands[-1] == (
        "curl",
        "-fsS",
        "http://ai-llm:8080/health",
    )


def test_composite_ocr_starts_vlm_before_api():
    runner = FakeRunner()

    manager(runner).start("ocr")

    starts = [command for command in runner.commands if command[:2] == ("docker", "start")]
    assert starts == [
        ("docker", "start", "ai-ocr-vlm"),
        ("docker", "start", "ai-ocr-api"),
    ]
    assert runner.running == {"ai-ocr-vlm", "ai-ocr-api"}


def test_composite_ocr_stops_in_reverse_order():
    runner = FakeRunner(running={"ai-ocr-vlm", "ai-ocr-api"})

    manager(runner).stop("ocr")

    stops = [command for command in runner.commands if command[:2] == ("docker", "stop")]
    assert stops == [
        ("docker", "stop", "ai-ocr-api"),
        ("docker", "stop", "ai-ocr-vlm"),
    ]
    assert runner.running == set()


def test_partial_ocr_start_failure_rolls_back_both_components():
    failing_url = "http://ai-ocr-api:8080/health"
    runner = FakeRunner(fail_health_urls={failing_url})

    with pytest.raises(RuntimeError, match="failed health check"):
        manager(runner).start("ocr")

    stops = [command for command in runner.commands if command[:2] == ("docker", "stop")]
    assert stops == [
        ("docker", "stop", "ai-ocr-api"),
        ("docker", "stop", "ai-ocr-vlm"),
    ]
    assert runner.running == set()


def test_unknown_service_raises_value_error():
    runner = FakeRunner()

    with pytest.raises(ValueError, match="Unknown service"):
        manager(runner).start("not-a-service")
