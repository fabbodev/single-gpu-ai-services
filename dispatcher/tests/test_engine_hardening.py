import subprocess
import sys
import time

import pytest

from engine_manager import EngineManager
from runner import SubprocessRunner


class ControlledRunner:
    def __init__(self):
        self.events = []
        self.running = set()
        self.unknown = set()
        self.fail_stop = set()
        self.fail_health = set()

    def run(self, *command, timeout=None):
        self.events.append((command, timeout))
        if command[:3] == ("docker", "inspect", "-f"):
            container = command[-1]
            if container in self.unknown:
                raise RuntimeError("docker daemon unavailable")
            if container in self.running:
                return "true\n"
            return "false\n"

        if command[:2] == ("docker", "start"):
            self.running.add(command[2])
            return ""
        if command[:2] == ("docker", "stop"):
            container = command[2]
            if container in self.fail_stop:
                raise RuntimeError(f"cannot stop {container}")
            self.running.discard(container)
            return ""

        if command[:2] == ("curl", "-fsS"):
            if command[-1] in self.fail_health:
                raise RuntimeError("health failed")
            return "ok"

        raise AssertionError(f"unexpected command: {command}")


def test_inspect_failure_is_not_silently_treated_as_stopped():
    runner = ControlledRunner()
    runner.unknown.add("ai-llm")
    manager = EngineManager(runner, health_interval=0)

    with pytest.raises(RuntimeError, match="state|inspect|unknown|unavailable"):
        manager.stop("llm", timeout=0.1)


def test_ocr_stop_attempts_every_component_even_after_one_fails():
    runner = ControlledRunner()
    runner.running.update({"ai-ocr-vlm", "ai-ocr-api"})
    runner.fail_stop.add("ai-ocr-api")
    manager = EngineManager(runner, health_interval=0)
    with pytest.raises(RuntimeError):
        manager.stop("ocr", timeout=0.2)

    stop_targets = [
        command[2]
        for command, _ in runner.events
        if command[:2] == ("docker", "stop")
    ]
    assert stop_targets == ["ai-ocr-api", "ai-ocr-vlm"]


def test_reconcile_stops_all_running_managed_engines():
    runner = ControlledRunner()
    runner.running.update({"ai-llm", "ai-ocr-vlm", "ai-ocr-api"})
    manager = EngineManager(runner, health_interval=0)

    manager.reconcile(timeout=0.3)

    assert runner.running == set()
    stop_targets = {
        command[2]
        for command, _ in runner.events
        if command[:2] == ("docker", "stop")
    }
    assert {"ai-llm", "ai-ocr-vlm", "ai-ocr-api"} <= stop_targets


def test_start_passes_bounded_timeouts_to_external_commands():
    runner = ControlledRunner()
    manager = EngineManager(runner, health_interval=0)

    manager.start("llm", timeout=0.2)
    relevant = [
        timeout
        for command, timeout in runner.events
        if command[0] in {"docker", "curl"}
    ]
    assert relevant
    assert all(timeout is not None and 0 < timeout <= 0.2 for timeout in relevant)


def test_subprocess_runner_enforces_timeout():
    runner = SubprocessRunner()
    started = time.monotonic()

    with pytest.raises(Exception):
        runner.run(
            sys.executable,
            "-c",
            "import time; time.sleep(2)",
            timeout=0.03,
        )

    assert time.monotonic() - started < 1.0


def test_start_failure_with_failed_cleanup_is_reported_as_cleanup_failure():
    runner = ControlledRunner()
    health = "http://ai-llm:8080/health"
    runner.fail_health.add(health)
    runner.fail_stop.add("ai-llm")
    manager = EngineManager(runner, health_attempts=1, health_interval=0)

    with pytest.raises(RuntimeError) as exc_info:
        manager.start("llm", timeout=0.2)

    message = str(exc_info.value).lower()
    assert "cleanup" in message or "stop" in message
    assert "ai-llm" in runner.running


def test_timed_out_docker_start_is_reported_as_uncertain_lifecycle():
    from engine_manager import EngineCleanupError
    from runner import CommandTimeout

    class StartTimeoutRunner(ControlledRunner):
        def run(self, *command, timeout=None):
            if command[:2] == ("docker", "start"):
                self.events.append((command, timeout))
                raise CommandTimeout(
                    "simulated start timeout",
                    command=command,
                )
            return super().run(*command, timeout=timeout)

    runner = StartTimeoutRunner()
    manager = EngineManager(runner, health_interval=0)

    with pytest.raises(EngineCleanupError, match="uncertain|timed out|timeout"):
        manager.start("llm", timeout=0.1)
