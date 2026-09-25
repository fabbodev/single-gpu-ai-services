import base64
import binascii
import logging
import os
from typing import Any

import httpx
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_access_token

from auth import HashedTokenVerifier


GATEWAY_URL = os.getenv("GATEWAY_URL", "http://ai-gateway:8090")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("MCP_GATEWAY_TIMEOUT", "600"))
MAX_FILE_BYTES = int(os.getenv("MCP_MAX_FILE_BYTES", str(64 * 1024 * 1024)))
CLIENT_TOKENS_FILE = os.getenv(
    "AI_CLIENT_TOKENS_FILE",
    "/run/secrets/client-tokens.json",
)
auth_logger = logging.getLogger("ai.mcp.auth")
auth_logger.setLevel(logging.INFO)
if not auth_logger.handlers:
    auth_handler = logging.StreamHandler()
    auth_handler.setLevel(logging.INFO)
    auth_handler.setFormatter(
        logging.Formatter("%(levelname)s %(name)s %(message)s")
    )
    auth_logger.addHandler(auth_handler)

PUBLIC_STT_MODEL = "faster-whisper-large-v3"
PUBLIC_TTS_MODEL = "coqui-es-css10-vits"
PUBLIC_EMBEDDINGS_MODEL = "bge-m3"
PUBLIC_RERANK_MODEL = "bge-reranker-v2-m3"
PUBLIC_OCR_MODEL = "paddleocr-vl-1.6"


def decode_base64_payload(value: str, *, max_bytes: int = MAX_FILE_BYTES) -> bytes:
    """Decode a bounded base64 MCP argument and fail clearly on malformed input."""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    max_encoded = ((max_bytes + 2) // 3) * 4
    if len(value) > max_encoded:
        raise ValueError("base64 payload too large")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid base64 payload") from exc
    if len(decoded) > max_bytes:
        raise ValueError("base64 payload too large")
    return decoded


class GatewayClient:
    """Thin HTTP client for the stable AI Services Gateway REST API."""

    def __init__(
        self,
        base_url: str = GATEWAY_URL,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    def _client(self, bearer_token: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            transport=self.transport,
            headers={"Authorization": f"Bearer {bearer_token}"},
        )

    async def embed_text(self, input: str | list[str], *, bearer_token: str) -> dict[str, Any]:
        async with self._client(bearer_token) as client:
            response = await client.post(
                "/v1/embeddings",
                json={"model": PUBLIC_EMBEDDINGS_MODEL, "input": input},
            )
            response.raise_for_status()
            return response.json()

    async def rerank_documents(self, query: str, documents: list[str], *, bearer_token: str) -> dict[str, Any]:
        async with self._client(bearer_token) as client:
            response = await client.post(
                "/v1/rerank",
                json={
                    "model": PUBLIC_RERANK_MODEL,
                    "query": query,
                    "documents": documents,
                },
            )
            response.raise_for_status()
            return response.json()

    async def read_document(
        self,
        filename: str,
        content_base64: str,
        content_type: str,
        *,
        bearer_token: str,
    ) -> dict[str, Any]:
        file_bytes = decode_base64_payload(content_base64)
        files = {"file": (filename, file_bytes, content_type)}
        data = {"model": PUBLIC_OCR_MODEL}
        async with self._client(bearer_token) as client:
            response = await client.post("/v1/documents/read", files=files, data=data)
            response.raise_for_status()
            return response.json()

    async def transcribe_audio(
        self,
        filename: str,
        content_base64: str,
        content_type: str,
        language: str | None = None,
        *,
        bearer_token: str,
    ) -> dict[str, Any]:
        audio_bytes = decode_base64_payload(content_base64)
        files = {"file": (filename, audio_bytes, content_type)}
        data = {"model": PUBLIC_STT_MODEL}
        if language:
            data["language"] = language
        async with self._client(bearer_token) as client:
            response = await client.post(
                "/v1/audio/transcriptions",
                files=files,
                data=data,
            )
            response.raise_for_status()
            return response.json()

    async def generate_speech(self, text: str, *, bearer_token: str) -> dict[str, str]:
        async with self._client(bearer_token) as client:
            response = await client.post(
                "/v1/audio/speech",
                json={
                    "model": PUBLIC_TTS_MODEL,
                    "input": text,
                    "response_format": "wav",
                },
            )
            response.raise_for_status()
            return {
                "media_type": response.headers.get("content-type", "audio/wav").split(";", 1)[0],
                "audio_base64": base64.b64encode(response.content).decode(),
            }


gateway_client = GatewayClient()
token_verifier = HashedTokenVerifier.from_file(
    CLIENT_TOKENS_FILE,
    required_scopes=["mcp"],
)
mcp = FastMCP(
    "single-gpu-ai-services",
    auth=token_verifier,
)


def current_client():
    access = get_access_token()
    if access is None:
        raise RuntimeError("authenticated MCP access token required")
    return access


@mcp.tool
async def read_document(filename: str, content_base64: str, content_type: str) -> dict[str, Any]:
    """Read a PDF or image with the GPU OCR service.

    The caller must provide the file bytes as base64 because the MCP server may
    run on a different machine from the agent and cannot dereference a client-local path.
    """
    access = current_client()
    auth_logger.info("client_id=%s tool=read_document", access.client_id)
    return await gateway_client.read_document(
        filename,
        content_base64,
        content_type,
        bearer_token=access.token,
    )


@mcp.tool
async def transcribe_audio(
    filename: str,
    content_base64: str,
    content_type: str,
    language: str | None = None,
) -> dict[str, Any]:
    """Transcribe audio with the GPU speech-to-text service."""
    access = current_client()
    auth_logger.info("client_id=%s tool=transcribe_audio", access.client_id)
    return await gateway_client.transcribe_audio(
        filename,
        content_base64,
        content_type,
        language=language,
        bearer_token=access.token,
    )


@mcp.tool
async def generate_speech(text: str) -> dict[str, str]:
    """Generate a WAV speech file and return it as base64."""
    access = current_client()
    auth_logger.info("client_id=%s tool=generate_speech", access.client_id)
    return await gateway_client.generate_speech(
        text,
        bearer_token=access.token,
    )


@mcp.tool
async def embed_text(input: str | list[str]) -> dict[str, Any]:
    """Create embeddings for one string or a list of strings."""
    access = current_client()
    auth_logger.info("client_id=%s tool=embed_text", access.client_id)
    return await gateway_client.embed_text(
        input,
        bearer_token=access.token,
    )


@mcp.tool
async def rerank_documents(query: str, documents: list[str]) -> dict[str, Any]:
    """Rerank candidate documents by relevance to a query."""
    access = current_client()
    auth_logger.info("client_id=%s tool=rerank_documents", access.client_id)
    return await gateway_client.rerank_documents(
        query,
        documents,
        bearer_token=access.token,
    )


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8091)
