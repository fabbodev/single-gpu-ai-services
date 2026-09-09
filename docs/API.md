# REST API

The Gateway listens on port `8090` in the reference configuration.

Examples below use:

```text
http://localhost:8090
```

## Health

### `GET /health`

```bash
curl http://localhost:8090/health
```

Example response:

```json
{"status":"ok","service":"ai-services"}
```

## Models

### `GET /v1/models`

```bash
curl http://localhost:8090/v1/models
```

The current snapshot advertises:

- `qwen3-8b`
- `faster-whisper-large-v3`
- `coqui-es-css10-vits`
- `bge-m3`
- `bge-reranker-v2-m3`
- `paddleocr-vl-1.6`

## Chat completions

### `POST /v1/chat/completions`

Model: `qwen3-8b`

The Gateway accepts an OpenAI-style non-streaming chat payload and forwards supported fields to llama.cpp.

```bash
curl -s http://localhost:8090/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3-8b",
    "messages": [
      {"role": "user", "content": "Explain GPU memory in one sentence."}
    ],
    "temperature": 0.2,
    "max_tokens": 128
  }'
```

Supported forwarded fields in this snapshot:

```text
model
messages
temperature
max_tokens
top_p
stop
```

The Gateway forces `stream` to `false`.

## Speech-to-text

### `POST /v1/audio/transcriptions`

Model: `faster-whisper-large-v3`

Multipart fields:

- `file` — audio file
- `model` — optional; defaults to `faster-whisper-large-v3`
- `language` — optional language hint

```bash
curl -s http://localhost:8090/v1/audio/transcriptions \
  -F file=@sample.wav \
  -F model=faster-whisper-large-v3 \
  -F language=en
```

Response shape:

```json
{"text":"transcribed text"}
```

## Text-to-speech

### `POST /v1/audio/speech`

Model: `coqui-es-css10-vits`

Only WAV output is supported by this snapshot.

```bash
curl -s http://localhost:8090/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "coqui-es-css10-vits",
    "input": "Hola mundo",
    "response_format": "wav"
  }' \
  --output speech.wav
```

The response body is `audio/wav`.

## Embeddings

### `POST /v1/embeddings`

Model: `bge-m3`

```bash
curl -s http://localhost:8090/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "bge-m3",
    "input": "The sky is blue."
  }'
```

The Hugging Face Text Embeddings Inference response is forwarded by the Gateway.

## Reranking

### `POST /v1/rerank`

Model: `bge-reranker-v2-m3`

```bash
curl -s http://localhost:8090/v1/rerank \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "bge-reranker-v2-m3",
    "query": "What color is the sky?",
    "documents": [
      "The sky is blue.",
      "Cats are mammals.",
      "Snow is white."
    ]
  }'
```

Response shape:

```json
{
  "model": "bge-reranker-v2-m3",
  "results": [
    {"index": 0, "score": 0.95}
  ]
}
```

Exact scores depend on the model/runtime.

## Document OCR / parsing

### `POST /v1/documents/read`

Model: `paddleocr-vl-1.6`

Supported input classes:

- PDF (`application/pdf`)
- images (`image/*`)

```bash
curl -s http://localhost:8090/v1/documents/read \
  -F file=@document.pdf \
  -F model=paddleocr-vl-1.6
```

Response shape:

```json
{
  "model": "paddleocr-vl-1.6",
  "text": "parsed Markdown/text"
}
```

Internally the Gateway base64-encodes the uploaded bytes and calls the PaddleX layout-parsing API. Parsed page Markdown is joined with blank lines.

## Errors

Common Gateway behavior:

- unsupported public model: HTTP `400`
- unsupported OCR file type: HTTP `400`
- engine/backend HTTP failure after lease acquisition: HTTP `502`

When a backend request fails after the GPU lease was acquired, the Gateway releases the logical service in a `finally` block.
