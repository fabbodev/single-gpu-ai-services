import asyncio


class RequestCapacityLimiter:
    def __init__(self, limit: int):
        if limit <= 0:
            raise ValueError("request capacity limit must be positive")
        self.limit = limit
        self._active = 0
        self._lock = asyncio.Lock()

    async def try_acquire(self) -> bool:
        async with self._lock:
            if self._active >= self.limit:
                return False
            self._active += 1
            return True

    def release(self) -> None:
        if self._active <= 0:
            raise RuntimeError("capacity limiter release without acquire")
        self._active -= 1
