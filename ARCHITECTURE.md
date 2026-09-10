# Architecture

## Purpose

`single-gpu-ai-services` lets several AI capabilities share one NVIDIA GPU by keeping a stable API layer running while GPU-heavy engines are started only when needed.

## Components

```text
Client
  |
  v
AI Gateway :8090
  |
  v
GPU Dispatcher :8092
  |
  +-- ai-llm
  +-- ai-stt
  +-- ai-tts
  +-- ai-embeddings
  +-- ai-reranker
  +-- OCR logical service
       +-- ai-ocr-vlm
       +-- ai-ocr-api
```

All components share the Docker network `ai-services-internal`.

## Gateway

The Gateway is a FastAPI service that owns the public HTTP interface. It validates the requested public model id, asks the Dispatcher for the logical GPU lease, forwards the request to the selected backend, translates the response where needed, and releases the lease in a `finally` block after acquisition.

The Gateway does not mount the Docker socket and does not directly start or stop containers.

## Dispatcher

The Dispatcher is a private FastAPI service. It owns one `GPUDispatcher` instance protected by a `threading.Condition`.

`GPUDispatcher.acquire(service)` blocks while another logical service owns the GPU. Once the lease is free, it asks `EngineManager` to start the requested engine and then records that service as the current owner.

`GPUDispatcher.release(service)` verifies ownership, stops the engine, clears ownership, and wakes waiting requests.

This is intentionally simple arbitration. It is not a priority scheduler and does not attempt concurrent VRAM packing.

## EngineManager

`EngineManager` maps a logical service to one or more Docker containers and health URLs.

```text
llm        -> ai-llm
stt        -> ai-stt
tts        -> ai-tts
embeddings -> ai-embeddings
reranker   -> ai-reranker
ocr        -> ai-ocr-vlm + ai-ocr-api
```

On start it:

1. checks whether each required container is already running;
2. starts it with `docker start` when required;
3. waits for the service health endpoint;
4. proceeds to the next component only after readiness.

If startup fails, it calls the stop path before re-raising the exception.

On release it stops components in reverse order.

## Why containers are created ahead of time

The Dispatcher deliberately uses `docker start` and `docker stop` rather than invoking `docker compose up` for every request. Engine containers therefore need to be created once during installation.

This separates two concerns:

- **installation/configuration:** Docker Compose creates the engine containers;
- **runtime arbitration:** Dispatcher starts and stops existing containers.

That makes the runtime path small and easy to inspect.

## Composite OCR

OCR is one logical lease implemented by two GPU-aware containers.

Startup:

```text
ai-ocr-vlm
  -> wait for http://ai-ocr-vlm:8080/health
  -> ai-ocr-api
  -> wait for http://ai-ocr-api:8080/health
```

Release:

```text
ai-ocr-api
  -> ai-ocr-vlm
```

Both containers belong to the same logical `ocr` lease. Another service cannot acquire the GPU between the two OCR components.

## Request lifecycle example

```text
POST /v1/chat/completions
  |
  +-> Gateway validates model=qwen3-8b
  +-> POST ai-dispatcher:8092/acquire/llm
       |
       +-> wait while another service owns the lease
       +-> docker start ai-llm
       +-> wait for ai-llm health
  +-> POST ai-llm:8080/v1/chat/completions
  +-> return backend response
  +-> POST ai-dispatcher:8092/release/llm
       |
       +-> docker stop ai-llm
       +-> clear ownership
       +-> notify waiting requests
```

## Network boundary

The intended boundary is:

```text
host / trusted network
       |
       v
Gateway :8090
       |
       v
ai-services-internal Docker network
       |
       +-- Dispatcher
       +-- engine containers
```

The Dispatcher should not be published to the host unless the operator deliberately chooses to do so.

## Model storage

Model weights are kept outside Git and mounted read-only into engine containers. The reference root is:

```text
/opt/ai-services/models
```

This keeps code/configuration independent from large model assets and avoids leaking tokens or model caches into source control.

## Reference hardware

The design was verified on a single RTX 3080 with 10 GB VRAM. The OCR VLM required conservative vLLM memory settings to fit comfortably. Those values are stored in `engines/ocr/backend_config.yaml`.

The architecture itself is not specific to the RTX 3080; the memory tuning and viable model sizes are.
