from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from dispatcher import (
    DispatcherNotReady,
    GPUDispatcher,
    LeaseConflict,
    LeaseNotFound,
    StaleEpoch,
)
from engine_manager import EngineManager
from runner import SubprocessRunner


class AcquireRequest(BaseModel):
    request_id: str
    epoch: str
    wait_timeout: float = 30.0


class LeaseCommand(BaseModel):
    request_id: str
    epoch: str


app = FastAPI(title="AI Services Dispatcher")

dispatcher = GPUDispatcher(
    engine_manager=EngineManager(
        runner=SubprocessRunner(),
        health_attempts=60,
        health_interval=1,
        cleanup_timeout=60,
    ),
    max_queue_wait=30,
    startup_timeout=120,
    active_timeout=330,
    cleanup_timeout=60,
)


def _http_error(exc):
    if isinstance(exc, (StaleEpoch, LeaseConflict)):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, LeaseNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, DispatcherNotReady):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return exc


@app.get("/health")
def health():
    return {"status": "ok", "service": "dispatcher"}


@app.get("/ready")
def ready():
    return dispatcher.ready()
@app.post("/acquire/{service}")
def acquire(service: str, request: AcquireRequest):
    try:
        result = dispatcher.submit(
            service,
            request.request_id,
            request.epoch,
            wait_timeout=request.wait_timeout,
        )
    except Exception as exc:
        raise _http_error(exc)
    status_code = 200 if result["state"] == "active" else 202
    return JSONResponse(result, status_code=status_code)


@app.get("/leases/{request_id}")
def lease_status(
    request_id: str,
    epoch: str = Query(...),
):
    try:
        return dispatcher.get_lease(request_id, epoch)
    except Exception as exc:
        raise _http_error(exc)


@app.post("/release/{service}")
def release(service: str, request: LeaseCommand):
    try:
        result = dispatcher.release(
            service,
            request.request_id,
            request.epoch,
        )
    except Exception as exc:
        raise _http_error(exc)
    status_code = 200 if result["state"] == "released" else 202
    return JSONResponse(result, status_code=status_code)


@app.post("/cancel/{service}")
def cancel(service: str, request: LeaseCommand):
    try:
        result = dispatcher.cancel(
            service,
            request.request_id,
            request.epoch,
        )
    except Exception as exc:
        raise _http_error(exc)
    status_code = 200 if result["state"] == "cancelled" else 202
    return JSONResponse(result, status_code=status_code)
