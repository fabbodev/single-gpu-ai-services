import time

from runner import CommandFailed, CommandTimeout


class EngineCleanupError(RuntimeError):
    pass


class EngineManager:
    SERVICES = {
        "stt": [("ai-stt", "http://ai-stt:8000/health")],
        "tts": [("ai-tts", "http://ai-tts:5002/")],
        "llm": [("ai-llm", "http://ai-llm:8080/health")],
        "embeddings": [("ai-embeddings", "http://ai-embeddings:8080/health")],
        "reranker": [("ai-reranker", "http://ai-reranker:8080/health")],
        "ocr": [
            ("ai-ocr-vlm", "http://ai-ocr-vlm:8080/health"),
            ("ai-ocr-api", "http://ai-ocr-api:8080/health"),
        ],
    }

    def __init__(
        self,
        runner,
        health_attempts=60,
        health_interval=1,
        cleanup_timeout=60,
        clock=time.monotonic,
    ):
        self.runner = runner
        self.health_attempts = health_attempts
        self.health_interval = health_interval
        self.cleanup_timeout = cleanup_timeout
        self._clock = clock

    def has_service(self, service):
        return service in self.SERVICES

    def _get_components(self, service):
        try:
            return self.SERVICES[service]
        except KeyError as exc:
            raise ValueError(f"Unknown service: {service}") from exc

    def _remaining(self, deadline):
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise TimeoutError("engine lifecycle deadline exceeded")
        return remaining

    def _run(self, deadline, *command):
        return self.runner.run(
            *command,
            timeout=min(self._remaining(deadline), 10.0),
        )

    def _inspect_state(self, container, deadline):
        try:
            value = self._run(
                deadline,
                "docker",
                "inspect",
                "-f",
                "{{.State.Running}}",
                container,
            ).strip()
        except CommandFailed as exc:
            stderr = exc.stderr.lower()
            if "no such object" in stderr or "no such container" in stderr:
                return "missing"
            raise RuntimeError(
                f"container state unknown for {container}: {exc}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"container state unknown for {container}: {exc}"
            ) from exc

        if value == "true":
            return "running"
        if value == "false":
            return "stopped"
        raise RuntimeError(
            f"container state unknown for {container}: unexpected inspect output"
        )

    def _wait_until_healthy(self, service, health_url, deadline):
        last_error = None
        for _ in range(self.health_attempts):
            try:
                self.runner.run(
                    "curl",
                    "-fsS",
                    "--connect-timeout",
                    "2",
                    "--max-time",
                    str(max(1, min(5, int(self._remaining(deadline))))),
                    health_url,
                    timeout=min(self._remaining(deadline), 6.0),
                )
                return
            except Exception as exc:
                last_error = exc
                remaining = self._remaining(deadline)
                if self.health_interval:
                    time.sleep(min(self.health_interval, remaining))
        raise RuntimeError(
            f"Service {service} failed health check: {health_url}"
        ) from last_error

    def start(self, service, timeout):
        components = self._get_components(service)
        deadline = self._clock() + timeout
        try:
            for container, health_url in components:
                state = self._inspect_state(container, deadline)
                if state == "missing":
                    raise RuntimeError(
                        f"required engine container is missing: {container}"
                    )
                if state == "stopped":
                    self._run(deadline, "docker", "start", container)
                self._wait_until_healthy(service, health_url, deadline)
        except Exception as startup_error:
            ambiguous_start = (
                isinstance(startup_error, CommandTimeout)
                and startup_error.command[:2] == ("docker", "start")
            )
            try:
                self.stop(service, timeout=self.cleanup_timeout)
            except Exception as cleanup_error:
                raise EngineCleanupError(
                    f"startup failed for {service}; cleanup also failed: "
                    f"{cleanup_error}"
                ) from startup_error
            if ambiguous_start:
                raise EngineCleanupError(
                    f"docker start timed out for {service}; "
                    "lifecycle outcome is uncertain"
                ) from startup_error
            raise

    def stop(self, service, timeout):
        components = self._get_components(service)
        deadline = self._clock() + timeout
        self._stop_components(
            [container for container, _ in reversed(components)],
            deadline,
        )

    def reconcile(self, timeout):
        deadline = self._clock() + timeout
        containers = []
        for components in self.SERVICES.values():
            for container, _ in components:
                if container not in containers:
                    containers.append(container)
        self._stop_components(list(reversed(containers)), deadline)

    def _stop_components(self, containers, deadline):
        errors = []
        for container in containers:
            try:
                state = self._inspect_state(container, deadline)
            except Exception as exc:
                errors.append(f"{container}: {exc}")
                continue

            if state == "missing" or state == "stopped":
                continue

            try:
                self._run(deadline, "docker", "stop", container)
            except Exception as exc:
                errors.append(f"{container}: stop failed: {exc}")
                continue

            try:
                state = self._inspect_state(container, deadline)
                if state not in {"stopped", "missing"}:
                    errors.append(
                        f"{container}: still {state} after docker stop"
                    )
            except Exception as exc:
                errors.append(f"{container}: stop verification failed: {exc}")

        if errors:
            raise EngineCleanupError(
                "engine cleanup could not be verified: " + "; ".join(errors)
            )
