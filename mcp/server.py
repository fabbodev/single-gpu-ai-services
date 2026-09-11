import base64
import binascii
import os
from typing import Any

import httpx
from fastmcp import FastMCP


GATEWAY_URL = os.getenv("GATEWAY_URL", "http://ai-gateway:8090")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("MCP_GATEWAY_TIMEOUT", "300"))

PUBLIC_STT_MODEL = "faster-whisper-large-v3"
PUBLIC_TTS_MODEL = "coqui-es-css10-vits"
PUBLIC_EMBEDDINGS_MODEL = "bge-m3"
PUBLIC_RERANK_MODEL = "bge-reranker-v2-m3"
PUBLIC_OCR_MODEL = "paddleocr-vl-1.6"


def decode_base64_payload(value: str) -> bytes:
    """Decode a base64 MCP argument and fail clearly on malformed input."""
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid base64 payload") from exc


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

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            transport=self.transport,
        )

    async def embed_text(self, input: str | list[str]) -> dict[str, Any]:
        async with self._client() as client:
            response = await client.post(
                "/v1/embeddings",
                json={"model": PUBLIC_EMBEDDINGS_MODEL, "input": input},
            )
            response.raise_for_status()
            return response.json()

    async def rerank_documents(self, query: str, documents: list[str]) -> dict[str, Any]:
        async with self._client() as client:
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
    ) -> dict[str, Any]:
        file_bytes = decode_base64_payload(content_base64)
        files = {"file": (filename, file_bytes, content_type)}
        data = {"model": PUBLIC_OCR_MODEL}
        async with self._client() as client:
            response = await client.post("/v1/documents/read", files=files, data=data)
            response.raise_for_status()
            return response.json()

    async def transcribe_audio(
        self,
        filename: str,
        content_base64: str,
        content_type: str,
        language: str | None = None,
    ) -> dict[str, Any]:
        audio_bytes = decode_base64_payload(content_base64)
        files = {"file": (filename, audio_bytes, content_type)}
        data = {"model": PUBLIC_STT_MODEL}
        if language:
            data["language"] = language
        async with self._client() as client:
            response = await client.post(
                "/v1/audio/transcriptions",
                files=files,
                data=data,
            )
            response.raise_for_status()
            return response.json()

    async def generate_speech(self, text: str) -> dict[str, str]:
        async with self._client() as client:
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
mcp = FastMCP("single-gpu-ai-services")


@mcp.tool
aasync def _placeholder():
    pass
