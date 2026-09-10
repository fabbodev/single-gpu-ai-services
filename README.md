# single-gpu-ai-services

A reference implementation for sharing one NVIDIA GPU between multiple local AI services without keeping every model loaded at the same time.

The project exposes one stable REST Gateway while a private Dispatcher starts the requested GPU engine on demand, waits until it is ready, gives it exclusive logical use of the GPU, and stops it after the request completes.

The verified reference deployment used an **NVIDIA RTX 3080 10 GB**.

## Why this exists

A 10 GB GPU can run many useful models, but usually not all of them simultaneously. Instead of dedicating a GPU to every service, this project treats the GPU as a shared appliance:

```text
Clients
  |
  v
Gateway :8090
  |
  v
Dispatcher :8092 (internal only)
  |
  +-- LLM
  +-- STT
  +-- TTS
  +-- Embeddings
  +-- Reranker
  +-- OCR (two coordinated containers)
```

Only one logical service owns the GPU lease at a time. Competing requests wait rather than starting additional GPU-heavy engines concurrently.

## Implemented services

| Capability | Public model id | Engine |
|---|---|---|
| Chat / LLM | `qwen3-8b` | llama.cpp CUDA + Qwen3-8B Q4_K_M |
| Speech-to-text | `faster-whisper-large-v3` | Speaches / faster-whisper |
| Text-to-speech | `coqui-es-css10-vits` | Coqui TTS |
| Embeddings | `bge-m3` | Hugging Face Text Embeddings Inference |
| Reranking | `bge-reranker-v2-m3` | Hugging Face Text Embeddings Inference |
| OCR / document reading | `paddleocr-vl-1.6` | PaddleOCR-VL + PaddleX |

## Public REST endpoints

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

The Gateway is intentionally similar to familiar OpenAI-style HTTP surfaces where practical, but it is not intended to be a complete OpenAI API clone.

## GPU lifecycle

For a normal request:

```text
request
  -> Gateway acquire(service)
  -> Dispatcher waits until the logical GPU lease is free
  -> Dispatcher starts the engine container(s)
  -> Dispatcher waits for readiness
  -> Gateway performs inference
  -> Gateway release(service) in finally
  -> Dispatcher stops the engine container(s)
```

The `finally` release is important: backend failures should still relinquish the lease and stop the engine after acquisition.

## Composite OCR

OCR is one logical service backed by two containers:

```text
ai-ocr-vlm -> health -> ai-ocr-api -> health
```

It releases in reverse order:

```text
ai-ocr-api -> ai-ocr-vlm
```

If startup partially succeeds and a later OCR component fails, the EngineManager performs cleanup before propagating the failure.

The verified RTX 3080 10 GB VLM tuning is in `engines/ocr/backend_config.yaml`:

```yaml
gpu-memory-utilization: 0.60
max-model-len: 16384
max-num-batched-tokens: 8192
api-server-count: 1
```

In the reference deployment OCR used roughly 6.9-7.3 GB VRAM during operation.

## Installation philosophy

This repository deliberately does **not** hide the system behind a one-click installation script. The goal is to make the architecture understandable and reproducible.

Start here:

**[`docs/INSTALL.md`](docs/INSTALL.md)**

It walks through, in order:

1. NVIDIA driver verification
2. Docker and NVIDIA Container Toolkit verification
3. repository placement
4. internal Docker network creation
5. model directory preparation
6. engine container creation
7. Dispatcher startup
8. Gateway startup
9. per-engine API tests
10. idle-state verification

## Models are not included

No model weights, Hugging Face tokens, API credentials, private caches, or large binary assets are stored in this repository.

See [`docs/MODELS.md`](docs/MODELS.md) for the expected model layout and responsibilities.

## TTS note

The verified private deployment used a locally built Coqui TTS GPU image named `ai-services/coqui-tts:1.0`. Its original image build recipe was not preserved in the source mirror.

Rather than inventing a supposedly tested Dockerfile, this repository states that limitation explicitly. TTS remains optional until the operator supplies a compatible image with the expected `tts-server` path. See the installation guide.

The other engine definitions use published container images.

## Security boundary

Only the Dispatcher mounts the Docker socket:

```text
/var/run/docker.sock
```

The Gateway does not receive Docker control. The Dispatcher should remain on the private Docker network and should not be published directly to untrusted networks.

Docker socket access is effectively host-level control. Read [`SECURITY.md`](SECURITY.md) before exposing the Gateway beyond a trusted LAN/VPN/reverse proxy.

## Verification history

The private reference implementation was live-tested on 2026-09-08 with:

```text
Dispatcher tests: 21 passed
Gateway tests:    24 passed
```

Live verification also covered LLM, STT, TTS, embeddings, reranking, image OCR, PDF OCR, and exclusive handoff between OCR and LLM.

Those numbers describe the verified private reference snapshot. They are not a claim that every future GPU, driver, model revision, or upstream container tag will behave identically.

## MCP

MCP is **not required** and is intentionally not part of the core project. The REST/OpenAPI Gateway is the primary interface.

If an MCP-capable client needs these services, an external REST/OpenAPI-to-MCP adapter can be placed in front of the Gateway. See [`docs/MCP.md`](docs/MCP.md).

## Documentation

- [`docs/INSTALL.md`](docs/INSTALL.md) — manual installation on an NVIDIA GPU host
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — component responsibilities and lifecycle
- [`SECURITY.md`](SECURITY.md) — Docker socket and exposure model
- [`docs/API.md`](docs/API.md) — endpoint contracts and examples
- [`docs/MODELS.md`](docs/MODELS.md) — model files and directory layout
- [`docs/MCP.md`](docs/MCP.md) — optional MCP integration

## Project status

This is a **reference implementation**, not a universal plug-and-play appliance. It is intentionally small enough to read, modify, and adapt to a different NVIDIA GPU or model set.

Licensed under Apache-2.0.
