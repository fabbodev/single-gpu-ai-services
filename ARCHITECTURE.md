# Architecture

`single-gpu-ai-services` separates a stable client-facing API from GPU lifecycle control and engine-specific inference runtimes.

```text
Clients
  |
  v
AI Services Gateway :8090
  |
  v
GPU Dispatcher :8092 (Docker-internal only)
  |
  +--> llm        -> ai-llm
  +--> stt        -> ai-stt
  +--> tts        -> ai-tts
  +--> embeddings -> ai-embeddings
  +--> reranker   -> ai-reranker
  +--> ocr        -> ai-ocr-vlm + ai-ocr-api
```

## Design goals

The reference deployment was built for a constrained single-GPU host where several useful AI services fit individually, but keeping every engine resident at the same time would exceed available VRAM.

The design therefore treats GPU access as one exclusive logical lease.

A request follows this lifecycle:

```text
request
  -> Gateway validates the public request
  -> Gateway asks Dispatcher to acquire a logical service
  -> Dispatcher waits while another service owns the GPU
  -> EngineManager starts the requested container component(s)
  -> EngineManager waits for readiness
  -> Gateway calls the engine-specific API
  -> Gateway releases the logical service in finally
  -> EngineManager stops the component(s)
  -> Dispatcher clears ownership and wakes waiters
```

Competing requests block/queue rather than intentionally running multiple GPU-heavy logical services at once.

## Gateway

The Gateway is implemented with FastAPI and exposes the stable REST surface:

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

The Gateway is responsible for:

- public request validation
- stable public model IDs
- translation to engine-specific request formats
- acquiring/releasing GPU leases through Dispatcher
- translating backend failures to gateway responses

The Gateway deliberately has no Docker socket access.

## Dispatcher

The Dispatcher exposes only an internal control API:

```text
GET  /health
POST /acquire/{service}
POST /release/{service}
```

`GPUDispatcher` uses a `threading.Condition` and a single `current_service` owner. `acquire()` waits until ownership is free. `release()` verifies ownership, stops the engine, clears the lease, and wakes waiting requests.

The Dispatcher is the only project component that receives `/var/run/docker.sock`.

## EngineManager

`EngineManager` maps logical services to one or more Docker containers and readiness URLs.

```text
llm        -> ai-llm
stt        -> ai-stt
tts        -> ai-tts
embeddings -> ai-embeddings
reranker   -> ai-reranker
ocr        -> ai-ocr-vlm + ai-ocr-api
```

For each component, startup is:

```text
inspect
-> docker start if stopped
-> wait for readiness
```

If startup fails, the manager invokes cleanup before propagating the error.

## Composite OCR service

OCR demonstrates why the lease is attached to a logical service rather than a single container.

```text
ocr
├── ai-ocr-vlm
└── ai-ocr-api
```

Acquire order:

```text
start ai-ocr-vlm
-> wait for VLM health
-> start ai-ocr-api
-> wait for API health
```

Release order is reversed:

```text
stop ai-ocr-api
-> stop ai-ocr-vlm
```

A partial startup failure triggers cleanup of any OCR components that were already started.

The OCR gateway endpoint accepts an image or PDF, base64-encodes the bytes for the PaddleX document pipeline, and returns the joined Markdown text from the parsed pages.

## Docker network

The reference configuration uses one external Docker network:

```text
ai-services-internal
```

Container DNS names are part of the application contract. The Dispatcher should remain reachable only inside this Docker network.

## Model storage

Model weights live outside application images and are not committed to this repository.

Reference layout:

```text
/opt/ai-services/models/
├── llm/
├── stt/
├── tts/
├── ocr/
├── embeddings/
└── reranker/
```

See `docs/MODELS.md` for the concrete model/configuration references used by this snapshot.

## Security invariants

1. Clients communicate with the Gateway, not the Dispatcher.
2. Dispatcher is not published as a host-facing service.
3. Only Dispatcher receives Docker socket access.
4. GPU engines use `restart: "no"` so the Dispatcher owns their runtime lifecycle.
5. Only one logical GPU service owns the lease at a time.
6. A logical service may contain multiple cooperating containers while consuming one lease.

See `SECURITY.md` for the operational security model.
