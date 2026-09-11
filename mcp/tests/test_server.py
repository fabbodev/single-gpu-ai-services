import base64
import json

import httpx
import pytest

from server import GatewayClient, decode_base64_payload


def make_gateway(handler):
    transport = httpx.MockTransport(handler)
    return GatewayClient(base_url="http://gateway.test", transport=transport)


def test_decode_base64_payload_rejects_invalid_input():
    with pytest.raises(ValueError, match="invalid base64"):
        decode_base64_payload("not-valid-base64!!!")


@pytest.mark.asyncio
async def test_embed_text_posts_openai_compatible_payload():
    async def handler(request):
        assert request.url.path == "/v1/embeddings"
        assert json.loads(request.content) == {"model": "bge-m3", "input": ["one", "two"]}
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})

    gateway = make_gateway(handler)
    result = await gateway.embed_text(["one", "two"])
    assert result["data"][0]["embedding"] == [0.1, 0.2]


@pytest.mark.asyncio
async def test_rerank_documents_posts_query_and_documents():
    async def handler(request):
        assert request.url.path == "/v1/rerank"
        assert json.loads(request.content) == {
            "model": "bge-reranker-v2-m3",
            "query": "best match",
            "documents": ["alpha", "beta"],
        }
        return httpx.Response(200, json={"results": [{"index": 1, "score": 0.9}]})

    gateway = make_gateway(handler)
    result = await gateway.rerank_documents("best match", ["alpha", "beta"])
    assert result["results"][0]["index"] == 1


@pytest.mark.asyncio
async def test_read_document_sends_decoded_file_as_multipart():
    payload = base64.b64encode(b"fake-pdf").decode()

    async def handler(request):
        assert request.url.path == "/v1/documents/read"
        assert b'filename="invoice.pdf"' in request.content
        assert b"fake-pdf" in request.content
        assert b'paddleocr-vl-1.6' in request.content
        return httpx.Response(200, json={"model": "paddleocr-vl-1.6", "text": "Invoice total 42"})

    gateway = make_gateway(handler)
    result = await gateway.read_document("invoice.pdf", payload, "application/pdf")
    assert result["text"] == "Invoice total 42"


@pytest.mark.asyncio
async def test_transcribe_audio_sends_audio_and_language():
    payload = base64.b64encode(b"fake-audio").decode()

    async def handler(request):
        assert request.url.path == "/v1/audio/transcriptions"
        assert b'filename="clip.wav"' in request.content
        assert b"fake-audio" in request.content
        assert b"faster-whisper-large-v3" in request.content
        assert b"es" in request.content
        return httpx.Response(200, json={"text": "hola"})

    gateway = make_gateway(handler)
    result = await gateway.transcribe_audio("clip.wav", payload, "audio/wav", language="es")
    assert result == {"text": "hola"}


@pytest.mark.asyncio
async def test_generate_speech_returns_base64_wav():
    async def handler(request):
        assert request.url.path == "/v1/audio/speech"
        assert json.loads(request.content) == {
            "model": "coqui-es-css10-vits",
            "input": "hola",
            "response_format": "wav",
        }
        return httpx.Response(200, content=b"RIFFfakewav", headers={"content-type": "audio/wav"})

    gateway = make_gateway(handler)
    result = await gateway.generate_speech("hola")
    assert result["media_type"] == "audio/wav"
    assert base64.b64decode(result["audio_base64"]) == b"RIFFfakewav"


@pytest.mark.asyncio
async def test_gateway_errors_are_not_silently_swallowed():
    async def handler(request):
        return httpx.Response(502, json={"detail": "backend unavailable"})

    gateway = make_gateway(handler)
    with pytest.raises(httpx.HTTPStatusError):
        await gateway.embed_text("hello")
