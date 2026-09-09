import threading


class GPUDispatcher:
    def __init__(self, engine_manager=None):
        self.current_service = None
        self._condition = threading.Condition()
        self._engine_manager = engine_manager

    def acquire(self, service: str):
        with self._condition:
            while self.current_service is not None:
                self._condition.wait()

            if self._engine_manager is not None:
                self._engine_manager.start(service)

            self.current_service = service

    def release(self, service: str):
        with self._condition:
            if self.current_service != service:
                raise RuntimeError(
                    f"Cannot release {service}: "
                    f"GPU is owned by {self.current_service}"
                )

            if self._engine_manager is not None:
                self._engine_manager.stop(service)

            self.current_service = None
            self._condition.notify_all()
