from fastapi import FastAPI

from dispatcher import GPUDispatcher
from engine_manager import EngineManager
from runner import SubprocessRunner


app = FastAPI(title="AI Services Dispatcher")

dispatcher = GPUDispatcher(
    engine_manager=EngineManager(
        runner=SubprocessRunner(),
        health_attempts=60,
        health_interval=1,
    )
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "dispatcher",
    }


@app.post("/acquire/{service}")
def acquire(service: str):
    dispatcher.acquire(service)

    return {
        "status": "acquired",
        "service": service,
    }


@app.post("/release/{service}")
def release(service: str):
    dispatcher.release(service)

    return {
        "status": "released",
        "service": service,
    }
