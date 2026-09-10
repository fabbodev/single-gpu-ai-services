import httpx


class DispatcherClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def acquire(self, service: str):
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{self.base_url}/acquire/{service}")
            response.raise_for_status()

    async def release(self, service: str):
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{self.base_url}/release/{service}")
            response.raise_for_status()
