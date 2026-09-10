import time


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

    def __init__(self, runner, health_attempts=60, health_interval=1):
        self.runner = runner
        self.health_attempts = health_attempts
        self.health_interval = health_interval

    def _get_components(self, service):
        try:
            return self.SERVICES[service]
        except KeyError as exc:
            raise ValueError(f"Unknown service: {service}") from exc

    def _is_running(self, container):
        try:
            return (
                self.runner.run(
                    "docker", "inspect", "-f", "{{.State.Running}}", container
                ).strip()
                == "true"
            )
        except Exception:
            return False

    def _wait_until_healthy(self, service, health_url):
        last_error = None
        for _ in range(self.health_attempts):
            try:
                self.runner.run("curl", "-fsS", health_url)
                return
            except Exception as exc:
                last_error = exc
                time.sleep(self.health_interval)
        raise RuntimeError(
            f"Service {service} failed health check: {health_url}"
        ) from last_error

    def start(self, service):
        components = self._get_components(service)
        try:
            for container, health_url in components:
                if not self._is_running(container):
                    self.runner.run("docker", "start", container)
                self._wait_until_healthy(service, health_url)
        except Exception:
            self.stop(service)
            raise

    def stop(self, service):
        components = self._get_components(service)
        for container, _ in reversed(components):
            if self._is_running(container):
                self.runner.run("docker", "stop", container)
