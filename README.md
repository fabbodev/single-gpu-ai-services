# single-gpu-ai-services

A reference implementation for serving multiple GPU-heavy AI capabilities through one stable REST API while allowing only one logical GPU workload at a time.

Engines are started on demand, checked for readiness, used, and stopped so a single constrained GPU can be shared across LLM, speech-to-text, text-to-speech, embeddings, reranking, and OCR/document parsing workloads.

> **Project status:** reference implementation, not a guaranteed plug-and-play installer.

## Why this exists

A single consumer GPU can run many useful AI models individually, but may not have enough VRAM to keep all of their runtimes resident simultaneously.

`single-gpu-ai-services` solves that problem with a small orchestration layer:

```text
Clients
  |
  v
Gateway :8090
  |
  v
Dispatcher :8092 (internal only)
  |
  +--> LLM
  +--> STT
  +--> TTS
  +--> Embeddings
  +--> Reranker
  +--> OCR (two coordinated containers)
```

The Dispatcher owns one logical GPU lease. A competing request waits until the current service releases the GPU.

## Core lifecycle

```text
request
  -> Gateway validates request
  -> acquire(service)
  -> wait until GPU lease is free
  -> start engine component(s)
  -> wait for readiness
  -> perform inference
  -> release(service) in finally
  -> stop engine component(s)
  -> wake waiting request(s)
```

This is the main purpose of the project. FastAPI provides the HTTP layer; the project-specific behavior is the GPU arbitration and container lifecycle around heterogeneous AI engines.

## Implemented services

| Capability | Public model ID | Reference engine |
| --- | --- | --- |
| LLM | `qwen3-8b` | llama.cpp CUDA |
| Speech-to-text | `faster-whisper-large-v3` | Speaches / faster-whisper |
| Text-to-speech | `coqui-es-css10-vits` | Coqui TTS-compatible server |
| Embeddings | `bge-m3` | Hugging Face TEI |
| Reranking | `bge-reranker-v2-m3` | Hugging Face TEI |
| OCR / document parsing | `paddleocr-vl-1.6` | PaddleOCR-VL + PaddleX |

OCR is a composite logical service:

```text
ocr
├── ai-ocr-vlm
└── ai-ocr-api
```

The VLM starts first, the API starts second, and shutdown happens in reverse order. Partial startup failures trigger cleanup.

## REST API

The stable Gateway endpoints are:

```text
GET  /health
GET  /v1/models
POST /v1/chat/completions
POST /v1/audio/transcriptions
POST /v1/audio/speech
POST /v1/embeddings
POST /v1/rerank
POST /v1/documents/read
```

Example:

```bash
curl -s http://localhost:8090/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3-8b",
    "messages": [
      {"role": "user", "content": "Say hello in one sentence."}
    ],
    "max_tokens": 64
  }'
```

See [`docs/API.md`](docs/API.md) for request/response details and examples.

## Reference hardware

The reference deployment was validated on an **NVIDIA RTX 3080 10 GB**.

The included OCR VLM settings were specifically tuned for that 10 GB reference deployment. Other GPUs may require different memory/context settings.

This project is not restricted to an RTX 3080; the core design is useful whenever multiple GPU-heavy services need to share one constrained accelerator.

## Requirements

The reference design assumes:

- Linux host or VM
- Docker Engine and Docker Compose
- NVIDIA GPU drivers
- NVIDIA Container Toolkit / working Docker GPU access
- enough local storage for model weights and caches
- model/runtime assets obtained separately from their upstream sources

Model weights are **not** committed to this repository.

## Reference filesystem layout

```text
/opt/ai-services/models/
├── llm/
├── stt/
├── tts/
├── ocr/
├── embeddings/
└── reranker/
```

The engine Compose files in this snapshot use that model layout.

See [`docs/MODELS.md`](docs/MODELS.md) for the exact model/runtime references.

## Reference deployment outline

The Dispatcher uses `docker start` / `docker stop`, so the engine containers must already exist before requests arrive.

A typical deployment flow is:

```bash
# Shared internal network
docker network create ai-services-internal

# After placing the required model files, create engine containers.
docker compose -f engines/llm/compose.yaml create
docker compose -f engines/stt/compose.yaml create
docker compose -f engines/embeddings/compose.yaml create
docker compose -f engines/reranker/compose.yaml create
docker compose -f engines/ocr/compose.yaml create

# TTS requires a compatible Coqui image; see docs/MODELS.md.
docker compose -f engines/tts/compose.yaml create

# Start the lifecycle controller and public API.
docker compose -f dispatcher/compose.yaml up -d --build
docker compose -f gateway/compose.yaml up -d --build
```

The OCR Compose file reflects the canonical `/opt/ai-services/engines/ocr` deployment layout for its configuration mounts. If you deploy elsewhere, adjust those host-side paths.

## Tests

The publication snapshot was re-verified from the code included here:

```text
Gateway unit tests:    14 passed
Dispatcher unit tests: 12 passed
Total:                 26 passed
```

The Dispatcher publication tests cover exclusive ownership behavior, blocking handoff, invalid release handling, start failure behavior, single-engine lifecycle, composite OCR ordering, reverse shutdown, and partial-start rollback.

These numbers intentionally replace older private-deployment test counts that were not fully preserved in the source snapshot used to create this repository.

## Security model

The Gateway does **not** receive Docker socket access.

The Dispatcher is the only component that mounts:

```text
/var/run/docker.sock
```

The Dispatcher should remain private to the Docker network. Docker socket access is effectively host-level administrative power, so exposing the Dispatcher directly would break an important security boundary.

The Gateway also has no built-in authentication in this reference implementation. Add an appropriate access-control layer before exposing it to untrusted networks.

See [`SECURITY.md`](SECURITY.md).

## MCP

MCP is intentionally not built into the core.

The REST/OpenAPI Gateway is the canonical interface. MCP-compatible agents can use an external adapter such as FastMCP or another REST/OpenAPI-to-MCP bridge without giving that adapter direct Docker control.

See [`docs/MCP.md`](docs/MCP.md).

## Known limitations

This repository preserves the architecture and runtime contracts of a working deployment rather than pretending to be a universal installer.

Notable snapshot-specific limitations include:

- model weights are not bundled
- several runtime images use mutable upstream tags and should be pinned for production
- the reference TTS service used a locally built image whose original build recipe was not present in the publication source snapshot
- Compose files assume the reference model directory layout unless edited
- authentication, TLS, quotas, observability, multi-GPU scheduling, and distributed locking are outside the current core

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — Gateway / Dispatcher / engine design
- [`docs/API.md`](docs/API.md) — REST contracts and examples
- [`docs/MODELS.md`](docs/MODELS.md) — model and runtime assets
- [`docs/MCP.md`](docs/MCP.md) — optional external MCP integration
- [`SECURITY.md`](SECURITY.md) — Docker socket and exposure model

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
