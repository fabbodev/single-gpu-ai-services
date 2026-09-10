from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Response
import base64
import httpx

from app.dispatcher_client import DispatcherClient


app = FastAPI(title="AI Services Gateway")

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


@app.get("/health")
def health():
    return {"status": "ok", "service": "ai-services"}


@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [
            {"id": PUBLIC_LLM_MODEL, "object": "model"},
            {"id": PUBLIC_STT_MODEL, "object": "model"},
            {"id": PUBLIC_TTS_MODEL, "object": "model"},
            {"id": PUBLIC_EMBEDDINGS_MODEL, "object": "model"},
            {"id": PUBLIC_RERANK_MODEL, "object": "model"},
            {"id": PUBLIC_OCR_MODEL, "object": "model"},
        ],
    }


@app.post("/v1/audio/transcriptions")
async def transcribe_audio(file: UploadFile = File(...), model: str = Form(PUBLIC_STT_MODEL), language: str | None = Form(None)):
    if model != PUBLIC_STT_MODEL:
        raise HTTPException(status_code=400, detail=f"Unsupported model: {model}")
    audio_bytes = await file.read()
    files = {"file": (file.filename or "audio", audio_bytes, file.content_type or "application/octet-stream")}
    data = {"model": ENGINE_STT_MODEL}
    if language:
        data["language"] = language
    acquired = False
    try:
        await dispatcher.acquire("stt")
        acquired = True
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(f"{STT_URL}/v1/audio/transcriptions", files=files, data=data)
            response.raise_for_status()
        return {"text": response.json().get("text", "")}
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"STT backend error: {exc}") from exc
    finally:
        if acquired:
            await dispatcher.release("stt")


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
    acquired = False
    try:
        await dispatcher.acquire("tts")
        acquired = True
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(f"{TTS_URL}/api/tts", params={"text": text})
            response.raise_for_status()
        return Response(content=response.content, media_type="audio/wav")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"TTS backend error: {exc}") from exc
    finally:
        if acquired:
            await dispatcher.release("tts")


@app.post("/v1/chat/completions")
async def chat_completions(payload: dict):
    model = payload.get("model", PUBLIC_LLM_MODEL)
    if model != PUBLIC_LLM_MODEL:
        raise HTTPException(status_code=400, detail=f"Unsupported model: {model}")
    backend_payload = {key: payload[key] for key in ("model", "messages", "temperature", "max_tokens", "top_p", "stop") if key in payload}
    backend_payload["model"] = PUBLIC_LLM_MODEL
    backend_payload["stream"] = False
    acquired = False
    try:
        await dispatcher.acquire("llm")
        acquired = True
        response = await http_client.post(f"{LLM_URL}/v1/chat/completions", json=backend_payload)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"LLM backend error: {exc}") from exc
    finally:
        if acquired:
            await dispatcher.release("llm")


@app.post("/v1/embeddings")
async def embeddings(payload: dict):
    model = payload.get("model", PUBLIC_EMBEDDINGS_MODEL)
    if model != PUBLIC_EMBEDDINGS_MODEL:
        raise HTTPException(status_code=400, detail=f"Unsupported model: {model}")
    backend_payload = {"model": PUBLIC_EMBEDDINGS_MODEL, "input": payload.get("input")}
    acquired = False
    try:
        await dispatcher.acquire("embeddings")
        acquired = True
        response = await http_client.post(f"{EMBEDDINGS_URL}/v1/embeddings", json=backend_payload)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Embeddings backend error: {exc}") from exc
    finally:
        if acquired:
            await dispatcher.release("embeddings")


@app.post("/v1/rerank")
async def rerank(payload: dict):
    model = payload.get("model", PUBLIC_RERANK_MODEL)
    if model != PUBLIC_RERANK_MODEL:
        raise HTTPException(status_code=400, detail=f"Unsupported model: {model}")
    backend_payload = {"query": payload.get("query"), "texts": payload.get("documents")}
    acquired = False
    try:
        await dispatcher.acquire("reranker")
        acquired = True
        response = await http_client.post(f"{RERANK_URL}/rerank", json=backend_payload)
        response.raise_for_status()
        return {"model": PUBLIC_RERANK_MODEL, "results": response.json()}
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Reranker backend error: {exc}") from exc
    finally:
        if acquired:
            await dispatcher.release("reranker")


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
    file_bytes = await file.read()
    backend_payload = {
        "file": base64.b64encode(file_bytes).decode(),
        "fileType": file_type,
        "visualize": False,
        "restructurePages": False,
    }
    acquired = False
    try:
        await dispatcher.acquire("ocr")
        acquired = True
        response = await http_client.post(f"{OCR_URL}/layout-parsing", json=backend_payload)
        response.raise_for_status()
        body = response.json()
        pages = body.get("result", {}).get("layoutParsingResults", [])
        text_parts = [page.get("markdown", {}).get("text", "") for page in pages]
        return {"model": PUBLIC_OCR_MODEL, "text": "\n\n".join(part for part in text_parts if part)}
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"OCR backend error: {exc}") from exc
    finally:
        if acquired:
            await dispatcher.release("ocr")
