# Manual installation guide

This project is intentionally documented as a set of understandable components rather than a one-click installer. The commands below show exactly what is created and why.

## 1. Reference hardware

The reference deployment was validated with one NVIDIA RTX 3080 with 10 GB VRAM. The design should also work on other NVIDIA GPUs with sufficient VRAM, but the OCR tuning in `engines/ocr/backend_config.yaml` was specifically validated on a 10 GB RTX 3080.

Recommended host resources:

- x86_64 Linux
- NVIDIA RTX 3080 10 GB or better
- 16 GB system RAM minimum; 32 GB recommended
- enough SSD space for model weights and Docker images
- Docker Engine with Docker Compose v2
- NVIDIA driver and NVIDIA Container Toolkit

## 2. Verify the NVIDIA driver

```bash
nvidia-smi
```

The RTX 3080 should appear and the command should complete without errors.

## 3. Verify Docker

```bash
docker --version
docker compose version
```

Then verify that Docker can access the GPU:

```bash
docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi
```

Do not continue until the GPU is visible inside the container.

## 4. Place the project

The reference compose files use `/opt/ai-services` as the canonical installation root.

```bash
sudo mkdir -p /opt/ai-services
sudo chown "$USER":"$USER" /opt/ai-services
git clone https://github.com/fabbodev/single-gpu-ai-services.git /opt/ai-services
cd /opt/ai-services
```

If you choose another root, update the host-side model paths in the engine compose files.

## 5. Create the internal Docker network

All components communicate over one Docker network. The Dispatcher itself is not published to the host.

```bash
docker network create ai-services-internal
```

If the network already exists, Docker will report that fact; no second network is required.

## 6. Create the model directories

```bash
mkdir -p models/llm
mkdir -p models/stt/hf-cache
mkdir -p models/tts/tts_models--es--css10--vits
mkdir -p models/embeddings/bge-m3
mkdir -p models/reranker/bge-reranker-v2-m3
mkdir -p models/ocr/paddle-data/official_models/PaddleOCR-VL-1.6
mkdir -p models/ocr/paddle-data/official_models/PP-DocLayoutV3
```

Expected layout:

```text
/opt/ai-services/
├── gateway/
├── dispatcher/
├── engines/
└── models/
    ├── llm/
    │   └── Qwen3-8B-Q4_K_M.gguf
    ├── stt/
    │   └── hf-cache/
    ├── tts/
    │   └── tts_models--es--css10--vits/
    │       ├── model_file.pth.tar
    │       └── config.json
    ├── embeddings/
    │   └── bge-m3/
    ├── reranker/
    │   └── bge-reranker-v2-m3/
    └── ocr/
        └── paddle-data/
            └── official_models/
                ├── PaddleOCR-VL-1.6/
                └── PP-DocLayoutV3/
```

Model weights are deliberately not included in this repository. Obtain them from their upstream publishers and review each model's license before use.

See `docs/MODELS.md` for the expected model families.

## 7. Prepare the TTS image

The verified private deployment used a locally built image named:

```text
ai-services/coqui-tts:1.0
```

The public compose file keeps that image name by default rather than pretending an unverified replacement is identical.

Before enabling TTS, build or provide a compatible Coqui TTS GPU image that contains a `tts-server` executable at `/opt/venv/bin/tts-server`, then tag it:

```bash
docker tag YOUR_COMPATIBLE_COQUI_IMAGE ai-services/coqui-tts:1.0
```

Alternatively set `TTS_IMAGE` when creating the TTS container if your compatible image has the same entrypoint/path contract:

```bash
TTS_IMAGE=your-registry/your-coqui-image:tag \
  docker compose -f engines/tts/compose.yaml create
```

TTS is the only engine in this reference snapshot whose original custom image build recipe was not preserved in the private code mirror. The repository documents this explicitly instead of inventing a supposedly tested recipe.

## 8. Create the engine containers

The Dispatcher controls containers with `docker start` and `docker stop`. Therefore the engine containers must exist before the Dispatcher receives traffic.

Create them without leaving them running:

```bash
docker compose -f engines/llm/compose.yaml create
docker compose -f engines/stt/compose.yaml create
# Run the next line only after preparing the TTS image.
docker compose -f engines/tts/compose.yaml create
docker compose -f engines/embeddings/compose.yaml create
docker compose -f engines/reranker/compose.yaml create
docker compose -f engines/ocr/compose.yaml create
```

Check that the expected containers exist:

```bash
docker ps -a --format 'table {{.Names}}\t{{.Status}}'
```

Expected names:

```text
ai-llm
ai-stt
ai-tts
ai-embeddings
ai-reranker
ai-ocr-vlm
ai-ocr-api
```

They should normally be stopped while idle.

## 9. Build and start the Dispatcher

```bash
cd /opt/ai-services/dispatcher
docker compose build
docker compose up -d
```

The Dispatcher has access to `/var/run/docker.sock` because it owns the engine lifecycle. This is a privileged trust boundary; read `SECURITY.md` before exposing anything outside the host.

Check it from inside the Docker network:

```bash
docker run --rm --network ai-services-internal curlimages/curl:latest \
  -fsS http://ai-dispatcher:8092/health
```

Expected response:

```json
{"status":"ok","service":"dispatcher"}
```

## 10. Build and start the Gateway

```bash
cd /opt/ai-services/gateway
docker compose build
docker compose up -d
```

The Gateway is the only project API that is intentionally published to the host, on port `8090`.

Verify:

```bash
curl -fsS http://localhost:8090/health
curl -fsS http://localhost:8090/v1/models
```

## 11. Test one engine at a time

### LLM

```bash
curl http://localhost:8090/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model":"qwen3-8b",
    "messages":[{"role":"user","content":"Reply with: GPU OK"}],
    "max_tokens":32
  }'
```

After the response, check that the engine stopped again:

```bash
docker inspect -f '{{.State.Running}}' ai-llm
```

Expected: `false`.

### Embeddings

```bash
curl http://localhost:8090/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"model":"bge-m3","input":"The sky is blue."}'
```

### Reranker

```bash
curl http://localhost:8090/v1/rerank \
  -H 'Content-Type: application/json' \
  -d '{
    "model":"bge-reranker-v2-m3",
    "query":"What color is the sky?",
    "documents":["The sky is blue.","Cats are mammals."]
  }'
```

### STT

```bash
curl http://localhost:8090/v1/audio/transcriptions \
  -F model=faster-whisper-large-v3 \
  -F file=@sample.wav
```

### TTS

```bash
curl http://localhost:8090/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"model":"coqui-es-css10-vits","input":"Hola mundo","response_format":"wav"}' \
  --output speech.wav
```

### OCR

```bash
curl http://localhost:8090/v1/documents/read \
  -F model=paddleocr-vl-1.6 \
  -F file=@sample.pdf
```

## 12. Confirm idle state

After requests complete:

```bash
for c in ai-llm ai-stt ai-tts ai-embeddings ai-reranker ai-ocr-vlm ai-ocr-api; do
  printf '%-18s ' "$c"
  docker inspect -f '{{.State.Running}}' "$c"
done

nvidia-smi
```

The design goal is that GPU-heavy engines are stopped when not in use.

## 13. How a request is handled

The important part of the system is intentionally visible:

```text
client
  -> Gateway receives request
  -> Gateway asks Dispatcher for the logical GPU lease
  -> Dispatcher waits if another service owns the GPU
  -> Dispatcher starts the required container(s)
  -> Dispatcher waits for readiness
  -> Gateway calls the engine
  -> Gateway releases in finally
  -> Dispatcher stops the engine container(s)
  -> next waiting service may acquire the GPU
```

There is no hidden scheduler and no MCP requirement. Read `ARCHITECTURE.md` and the Python files in `dispatcher/` if you want to change the arbitration behavior.
