from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, Response
from fastapi.responses import JSONResponse
import asyncio
import base64
import logging
import os
import httpx

from app.auth import ClientTokenStore, RegistryUnavailable
from app.chat_stream import buffered_sse
from app.dispatcher_client import DispatcherAcquireError, DispatcherClient
from app.limits import RequestCapacityLimiter


app = FastAPI(title="AI Services Gateway")

CLIENT_TOKENS_FILE = os.getenv(
    "AI_CLIENT_TOKENS_FILE",
    "/run/ai-clients/client-tokens.json",
)
client_tokens = ClientTokenStore.from_file(CLIENT_TOKENS_FILE)
auth_logger = logging.getLogger("ai.gateway.auth")
auth_logger.setLevel(logging.INFO)
if not auth_logger.handlers:
    auth_handler = logging.StreamHandler()
    auth_handler.setLevel(logging.INFO)
    auth_handler.setFormatter(
        logging.Formatter("%(levelname)s %(name)s %(message)s")
    )
    auth_logger.addHandler(auth_handler)

STT_URL = "http://ai-stt:8000"
DISPATCHER_URL = "http://ai-dispatcher:8092"

PUBLIC_STT_MODEL = "faster-whisper-large-v3"
ENGINE_STT_MODEL = "Systran/faster-whisper-large-v3"

TTS_URL = "http://ai-tts:5002"
PUBLIC_TTS_MODEL = "coqui-es-css10-vits"

LLM_URL = "http://ai-llm:8080"
PUBLIC_LLM_MODEL = "qwen3-8b"

EMBEDDINGS_URL = "http://ai-embeddings:8080"
PUBLIC_EMBEDDINGS_MODEL = "bge-m3"

RERANK_URL = "http://ai-reranker:8080"
PUBLIC_RERANK_MODEL = "bge-reranker-v2-m3"

OCR_URL = "http://ai-ocr-api:8080"
PUBLIC_OCR_MODEL = "paddleocr-vl-1.6"

dispatcher = DispatcherClient(DISPATCHER_URL)
http_client = httpx.AsyncClient(timeout=300.0)
INFERENCE_TIMEOUT_SECONDS = 300.0
MAX_INFLIGHT_REQUESTS = int(os.getenv("AI_MAX_INFLIGHT_REQUESTS", "8"))
MAX_OCR_UPLOAD_BYTES = int(os.getenv("AI_MAX_OCR_UPLOAD_BYTES", str(32 * 1024 * 1024)))
MAX_STT_UPLOAD_BYTES = int(os.getenv("AI_MAX_STT_UPLOAD_BYTES", str(128 * 1024 * 1024)))
request_limiter = RequestCapacityLimiter(MAX_INFLIGHT_REQUESTS)


@app.middleware("http")
async def authenticate_client(request: Request, call_next):
    if request.url.path in {"/health", "/ready"}:
        return await call_next(request)

    try:
        identity = client_tokens.authenticate(request.headers.get("authorization"))
    except RegistryUnavailable:
        return JSONResponse({"detail": "client registry unavailable"}, status_code=503)
    if identity is None:
        return JSONResponse(
            {"detail": "invalid or missing bearer token"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

    capability = {
        "/v1/chat/completions": "llm",
        "/v1/embeddings": "embeddings",
        "/v1/rerank": "reranker",
        "/v1/documents/read": "ocr",
        "/v1/audio/transcriptions": "stt",
        "/v1/audio/speech": "tts",
    }.get(request.url.path.rstrip("/"))
    required = {"gateway"} | ({capability} if capability else set())
    if not required.issubset(identity.scopes):
        return JSONResponse({"detail": "insufficient scope", "required_scopes": sorted(required)}, status_code=403)

    request.state.client_id = identity.client_id
    request.state.client_scopes = identity.scopes
    auth_logger.info(
        "client_id=%s method=%s path=%s",
        identity.client_id,
        request.method,
        request.url.path,
    )

    if request.method == "POST" and request.url.path.startswith("/v1/"):
        if not await request_limiter.try_acquire():
            return JSONResponse(
                {"detail": "too many in-flight AI requests"},
                status_code=429,
                headers={"Retry-After": "1"},
            )
        try:
            return await call_next(request)
        finally:
            request_limiter.release()

    return await call_next(request)


async def _read_upload_limited(file: UploadFile, max_bytes: int):
    chunks = bytearray()
    chunk_size = 1024 * 1024
    while True:
        remaining = max_bytes - len(chunks)
        chunk = await file.read(min(chunk_size, remaining + 1))
        if not chunk:
            return bytes(chunks)
        chunks.extend(chunk)
        if len(chunks) > max_bytes:
            raise HTTPException(status_code=413, detail="upload too large")


def _backend_json(response, service: str):
    try:
        return response.json()
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"{service} backend returned invalid JSON",
        ) from exc


async def _acquire_lease(service: str):
    try:
        return await dispatcher.acquire(service)
    except (DispatcherAcquireError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Dispatcher acquisition error: {exc}",
        ) from exc


async def _release_lease(lease):
    try:
        await asyncio.shield(dispatcher.release(lease))
    except (DispatcherAcquireError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Dispatcher release error: {exc}",
        ) from exc


@app.get("/health")
def health():
    return {"status": "ok", "service": "ai-services"}


@app.get("/ready")
async def ready():
    try:
        client_tokens.check_ready()
    except RegistryUnavailable:
        return JSONResponse({"ready": False, "reason": "client registry unavailable"}, status_code=503)
    try:
        body = await dispatcher.ready()
    except (DispatcherAcquireError, httpx.HTTPError) as exc:
        return JSONResponse(
            {"ready": False, "reason": str(exc)},
            status_code=503,
        )
    status_code = 200 if body.get("ready") else 503
    return JSONResponse(body, status_code=status_code)


@app.get("/v1/models")
def list_models(request: Request):
    models = [("llm", PUBLIC_LLM_MODEL), ("stt", PUBLIC_STT_MODEL),
              ("tts", PUBLIC_TTS_MODEL), ("embeddings", PUBLIC_EMBEDDINGS_MODEL),
              ("reranker", PUBLIC_RERANK_MODEL), ("ocr", PUBLIC_OCR_MODEL)]
    return {"object": "list", "data": [{"id": model, "object": "model"}
            for capability, model in models if capability in request.state.client_scopes]}


@app.post("/v1/audio/transcriptions")
async def transcribe_audio(file: UploadFile = File(...), model: str = Form(PUBLIC_STT_MODEL), language: str | None = Form(None)):
    if model != PUBLIC_STT_MODEL:
        raise HTTPException(status_code=400, detail=f"Unsupported model: {model}")
    audio_bytes = await _read_upload_limited(file, MAX_STT_UPLOAD_BYTES)
    files = {"file": (file.filename or "audio", audio_bytes, file.content_type or "application/octet-stream")}
    data = {"model": ENGINE_STT_MODEL}
    if language:
        data["language"] = language
    lease = await _acquire_lease("stt")
    try:
        async with asyncio.timeout(INFERENCE_TIMEOUT_SECONDS):
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(f"{STT_URL}/v1/audio/transcriptions", files=files, data=data)
                response.raise_for_status()
        body = _backend_json(response, "STT")
        text = body.get("text") if isinstance(body, dict) else None
        if not isinstance(text, str):
            raise HTTPException(
                status_code=502,
                detail="STT backend response missing text",
            )
        return {"text": text}
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="STT inference timed out") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"STT backend error: {exc}") from exc
    finally:
        await _release_lease(lease)


@app.post("/v1/audio/speech")
async def synthesize_speech(payload: dict):
    model = payload.get("model", PUBLIC_TTS_MODEL)
    text = payload.get("input", "")
    response_format = payload.get("response_format", "wav")
    if model != PUBLIC_TTS_MODEL:
        raise HTTPException(status_code=400, detail=f"Unsupported model: {model}")
    if not text:
        raise HTTPException(status_code=400, detail="input is required")
    if response_format != "wav":
        raise HTTPException(status_code=400, detail=f"Unsupported response_format: {response_format}")
    lease = await _acquire_lease("tts")
    try:
        async with asyncio.timeout(INFERENCE_TIMEOUT_SECONDS):
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(f"{TTS_URL}/api/tts", params={"text": text})
                response.raise_for_status()
        return Response(content=response.content, media_type="audio/wav")
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="TTS inference timed out") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"TTS backend error: {exc}") from exc
    finally:
        await _release_lease(lease)


@app.post("/v1/chat/completions")
async def chat_completions(payload: dict):
    stream = payload.get("stream", False)
    stream_options = payload.get("stream_options", {})
    if stream_options is None:
        stream_options = {}
    if type(stream) is not bool or not isinstance(stream_options, dict):
        raise HTTPException(status_code=400, detail="invalid stream or stream_options")
    if type(stream_options.get("include_usage", False)) is not bool:
        raise HTTPException(status_code=400, detail="include_usage must be boolean")
    if payload.get("n", 1) != 1:
        raise HTTPException(status_code=400, detail="only n=1 is supported")
    if "max_completion_tokens" in payload:
        if "max_tokens" in payload and payload["max_tokens"] != payload["max_completion_tokens"]:
            raise HTTPException(status_code=400, detail="conflicting output token limits")
        payload = dict(payload, max_tokens=payload["max_completion_tokens"])
    model = payload.get("model", PUBLIC_LLM_MODEL)
    if model != PUBLIC_LLM_MODEL:
        raise HTTPException(status_code=400, detail=f"Unsupported model: {model}")
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail="messages must be a non-empty list")
    allowed_fields = (
        "model",
        "messages",
        "temperature",
        "max_tokens",
        "top_p",
        "stop",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
    )
    backend_payload = {key: payload[key] for key in allowed_fields if key in payload}
    backend_payload["model"] = PUBLIC_LLM_MODEL
    backend_payload["stream"] = False
    lease = await _acquire_lease("llm")
    try:
        async with asyncio.timeout(INFERENCE_TIMEOUT_SECONDS):
            response = await http_client.post(f"{LLM_URL}/v1/chat/completions", json=backend_payload)
            response.raise_for_status()
        body = _backend_json(response, "LLM")
        if not isinstance(body, dict) or not isinstance(body.get("choices"), list):
            raise HTTPException(status_code=502, detail="LLM backend response has invalid schema")
        if stream:
            try:
                return buffered_sse(body, include_usage=stream_options.get("include_usage", False))
            except (ValueError, TypeError, AttributeError) as exc:
                raise HTTPException(status_code=502, detail="LLM backend response cannot be encoded as SSE") from exc
        return body
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="LLM inference timed out") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"LLM backend error: {exc}") from exc
    finally:
        await _release_lease(lease)


@app.post("/v1/embeddings")
async def embeddings(payload: dict):
    model = payload.get("model", PUBLIC_EMBEDDINGS_MODEL)
    if model != PUBLIC_EMBEDDINGS_MODEL:
        raise HTTPException(status_code=400, detail=f"Unsupported model: {model}")
    input_value = payload.get("input")
    valid_input = (
        isinstance(input_value, str) and bool(input_value.strip())
    ) or (
        isinstance(input_value, list)
        and 0 < len(input_value) <= 32
        and all(isinstance(item, str) and item.strip() for item in input_value)
    )
    if not valid_input:
        raise HTTPException(status_code=400, detail="input must be non-empty text or a list of up to 32 texts")
    backend_payload = {"model": PUBLIC_EMBEDDINGS_MODEL, "input": input_value}
    lease = await _acquire_lease("embeddings")
    try:
        async with asyncio.timeout(INFERENCE_TIMEOUT_SECONDS):
            response = await http_client.post(f"{EMBEDDINGS_URL}/v1/embeddings", json=backend_payload)
            response.raise_for_status()
        body = _backend_json(response, "Embeddings")
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise HTTPException(status_code=502, detail="Embeddings backend response has invalid schema")
        return body
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Embeddings inference timed out") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Embeddings backend error: {exc}") from exc
    finally:
        await _release_lease(lease)


@app.post("/v1/rerank")
async def rerank(payload: dict):
    model = payload.get("model", PUBLIC_RERANK_MODEL)
    if model != PUBLIC_RERANK_MODEL:
        raise HTTPException(status_code=400, detail=f"Unsupported model: {model}")
    query = payload.get("query")
    documents = payload.get("documents")
    if not isinstance(query, str) or not query.strip():
        raise HTTPException(status_code=400, detail="query is required")
    if not (
        isinstance(documents, list)
        and 0 < len(documents) <= 32
        and all(isinstance(item, str) and item.strip() for item in documents)
    ):
        raise HTTPException(status_code=400, detail="documents must contain 1 to 32 non-empty texts")
    backend_payload = {"query": query, "texts": documents}
    lease = await _acquire_lease("reranker")
    try:
        async with asyncio.timeout(INFERENCE_TIMEOUT_SECONDS):
            response = await http_client.post(f"{RERANK_URL}/rerank", json=backend_payload)
            response.raise_for_status()
        results = _backend_json(response, "Reranker")
        if not isinstance(results, list):
            raise HTTPException(status_code=502, detail="Reranker backend response has invalid schema")
        return {"model": PUBLIC_RERANK_MODEL, "results": results}
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Reranker inference timed out") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Reranker backend error: {exc}") from exc
    finally:
        await _release_lease(lease)


@app.post("/v1/documents/read")
async def read_document(file: UploadFile = File(...), model: str = Form(PUBLIC_OCR_MODEL)):
    if model != PUBLIC_OCR_MODEL:
        raise HTTPException(status_code=400, detail=f"Unsupported model: {model}")
    content_type = file.content_type or ""
    if content_type == "application/pdf":
        file_type = 0
    elif content_type.startswith("image/"):
        file_type = 1
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {content_type or 'unknown'}")
    file_bytes = await _read_upload_limited(file, MAX_OCR_UPLOAD_BYTES)
    backend_payload = {
        "file": base64.b64encode(file_bytes).decode(),
        "fileType": file_type,
        "visualize": False,
        "restructurePages": False,
    }
    lease = await _acquire_lease("ocr")
    try:
        async with asyncio.timeout(INFERENCE_TIMEOUT_SECONDS):
            response = await http_client.post(f"{OCR_URL}/layout-parsing", json=backend_payload)
            response.raise_for_status()
        body = _backend_json(response, "OCR")
        result = body.get("result") if isinstance(body, dict) else None
        pages = result.get("layoutParsingResults") if isinstance(result, dict) else None
        if not isinstance(pages, list):
            raise HTTPException(status_code=502, detail="OCR backend response has invalid schema")
        text_parts = []
        for page in pages:
            if not isinstance(page, dict):
                raise HTTPException(status_code=502, detail="OCR backend response has invalid page schema")
            markdown = page.get("markdown", {})
            if not isinstance(markdown, dict):
                raise HTTPException(status_code=502, detail="OCR backend response has invalid markdown schema")
            text = markdown.get("text", "")
            if not isinstance(text, str):
                raise HTTPException(status_code=502, detail="OCR backend response has invalid text schema")
            if text:
                text_parts.append(text)
        return {"model": PUBLIC_OCR_MODEL, "text": "\n\n".join(text_parts)}
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="OCR inference timed out") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"OCR backend error: {exc}") from exc
    finally:
        await _release_lease(lease)
