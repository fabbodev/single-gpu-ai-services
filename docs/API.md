# REST API

Default Gateway base URL in the reference deployment:

```text
http://localhost:8090
```

## Health

```http
GET /health
```

Example:

```bash
curl http://localhost:8090/health
```


## Authentication

All `/v1/*` endpoints require:

```http
Authorization: Bearer <bot-api-key>
```

`GET /health` and `GET /ready` are operational endpoints and do not require a bot key. Each bot should have its own key so access can be revoked and usage can be attributed independently.

For the examples below, load a bot key into the shell without placing it in source control:

```bash
read -rsp "AI API key: " AI_API_KEY; echo
```

Default control-plane limits are 8 concurrent AI requests, 32 MiB OCR uploads and 128 MiB STT uploads. Exceeding the concurrency limit returns HTTP 429; oversized uploads return HTTP 413.

## Models

```http
GET /v1/models
```

Returns the public model ids exposed by the Gateway.

```bash
curl http://localhost:8090/v1/models \
  -H "Authorization: Bearer $AI_API_KEY"
```

## Chat completions

```http
POST /v1/chat/completions
Content-Type: application/json
```

Reference model:

```text
qwen3-8b
```

Example:

```bash
curl http://localhost:8090/v1/chat/completions \
  -H "Authorization: Bearer $AI_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "model":"qwen3-8b",
    "messages":[{"role":"user","content":"Say hello."}],
    "temperature":0.2,
    "max_tokens":64
  }'
```

The Gateway currently forces non-streaming mode when forwarding to llama.cpp.

## Speech-to-text

```http
POST /v1/audio/transcriptions
Content-Type: multipart/form-data
```

Fields:

- `file`: audio file, required
- `model`: optional, defaults to `faster-whisper-large-v3`
- `language`: optional

Example:

```bash
curl http://localhost:8090/v1/audio/transcriptions \
  -H "Authorization: Bearer $AI_API_KEY" \
  -F model=faster-whisper-large-v3 \
  -F language=en \
  -F file=@sample.wav
```

Response shape:

```json
{"text":"..."}
```

## Text-to-speech

```http
POST /v1/audio/speech
Content-Type: application/json
```

Example:

```bash
curl http://localhost:8090/v1/audio/speech \
  -H "Authorization: Bearer $AI_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "model":"coqui-es-css10-vits",
    "input":"Hola mundo",
    "response_format":"wav"
  }' \
  --output speech.wav
```

The reference implementation accepts `wav` output.

## Embeddings

```http
POST /v1/embeddings
Content-Type: application/json
```

Example:

```bash
curl http://localhost:8090/v1/embeddings \
  -H "Authorization: Bearer $AI_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"bge-m3","input":"The sky is blue."}'
```

The backend response is forwarded by the Gateway.

## Reranking

```http
POST /v1/rerank
Content-Type: application/json
```

Example:

```bash
curl http://localhost:8090/v1/rerank \
  -H "Authorization: Bearer $AI_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "model":"bge-reranker-v2-m3",
    "query":"What color is the sky?",
    "documents":["The sky is blue.","Cats are mammals."]
  }'
```

Response shape:

```json
{
  "model":"bge-reranker-v2-m3",
  "results":[
    {"index":0,"score":0.95}
  ]
}
```

## OCR / document reading

```http
POST /v1/documents/read
Content-Type: multipart/form-data
```

Fields:

- `file`: image or PDF, required
- `model`: optional, defaults to `paddleocr-vl-1.6`

Example:

```bash
curl http://localhost:8090/v1/documents/read \
  -H "Authorization: Bearer $AI_API_KEY" \
  -F model=paddleocr-vl-1.6 \
  -F file=@document.pdf
```

Response shape:

```json
{
  "model":"paddleocr-vl-1.6",
  "text":"extracted markdown/text"
}
```

The Gateway translates uploads to the PaddleX backend format and joins page markdown text into one response.

## Error behavior

Unsupported public model ids return HTTP 400 before acquiring the GPU lease.

Unsupported OCR MIME classes also return HTTP 400 before acquisition.

Backend HTTP/transport failures are translated to HTTP 502. After a lease has been acquired, Gateway routes release the logical service in `finally`.

## Dispatcher API

The Dispatcher API is a private implementation detail and should remain on the internal Docker network. Protocol version 2 uses identified, idempotent leases:

```text
GET  /health
GET  /ready
POST /acquire/{service}
GET  /leases/{request_id}?epoch=<epoch>
POST /release/{service}
POST /cancel/{service}
```

`/ready` returns the current Dispatcher epoch, protocol version, readiness and degradation reason. Acquire requests include `request_id`, `epoch`, and a queue deadline. Release and cancel require the same `request_id` and `epoch`, preventing late commands from affecting a newer lease.

A normal acquire may return `202` while the request is queued or starting. Gateway polls the lease until it becomes `active` or reaches a terminal state. Stale epochs or conflicting request identities are rejected rather than silently reused.

Clients should call the Gateway rather than the Dispatcher directly. The Dispatcher API is not an authentication boundary; transport/auth hardening is handled separately from this lifecycle protocol.
