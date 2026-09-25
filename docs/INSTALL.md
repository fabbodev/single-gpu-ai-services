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

## 7. Build the pinned TTS runtime

From the repository root, run `docker compose -f engines/tts/compose.yaml build`.
The current recipe and lockfiles produce `ai-services/coqui-tts:0.27.5-cu128`.
Do not substitute the historical 1.0 image. Provision and verify the locked model
payloads as described in `reproducibility/README.md` before creating engines.

## 7a. Create runtime authentication

Follow [AUTH.md](AUTH.md) as the host registry owner. New installations use the
local `scripts/ai-client init` and `create` commands. Existing v1 installations
must explicitly migrate the old registry before recreating Gateway and MCP.

The new registry is `/etc/ai-services/clients/client-tokens.json` (v2). Its dedicated
parent directory is mounted read-only into Gateway/MCP at `/run/ai-clients`.
Keep the Dispatcher secret separately at `/etc/ai-services/secrets/dispatcher-token`.
Plaintext bot keys must not be placed in the mounted registry directory.

Protected directories use mode 0700; secret files use 0400. Bind addresses are
non-secret settings in `/etc/ai-services/runtime.env`:

```text
GATEWAY_BIND_ADDRESS=<trusted-private-ip>
MCP_BIND_ADDRESS=<trusted-private-ip>
AI_SECRETS_DIR=/etc/ai-services/secrets
AI_CLIENT_REGISTRY_DIR=/etc/ai-services/clients
```

Use `docker compose --env-file /etc/ai-services/runtime.env ...` in an appropriately
privileged operator session. The first code/mount upgrade requires Gateway/MCP
recreation. Routine credential edits after that are hot-reloaded without restart.
For manual tests, securely load a client key into `AI_API_KEY`; never echo it.

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
docker compose --env-file /etc/ai-services/runtime.env build
docker compose --env-file /etc/ai-services/runtime.env up -d
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
docker compose --env-file /etc/ai-services/runtime.env build
docker compose --env-file /etc/ai-services/runtime.env up -d
```

Gateway publishes port `8090`; optional MCP publishes `8091`. Both must use a trusted private bind address. Dispatcher remains unexposed.

Verify:

```bash
curl -fsS "http://$GATEWAY_BIND_ADDRESS:8090/health"
curl -fsS "http://$GATEWAY_BIND_ADDRESS:8090/v1/models" \
  -H "Authorization: Bearer $AI_API_KEY"
```

## 11. Test one engine at a time

### LLM

```bash
curl http://localhost:8090/v1/chat/completions \
  -H "Authorization: Bearer $AI_API_KEY" \
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
  -H "Authorization: Bearer $AI_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"bge-m3","input":"The sky is blue."}'
```

### Reranker

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

### STT

```bash
curl http://localhost:8090/v1/audio/transcriptions \
  -H "Authorization: Bearer $AI_API_KEY" \
  -F model=faster-whisper-large-v3 \
  -F file=@sample.wav
```

### TTS

```bash
curl http://localhost:8090/v1/audio/speech \
  -H "Authorization: Bearer $AI_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"coqui-es-css10-vits","input":"Hola mundo","response_format":"wav"}' \
  --output speech.wav
```

### OCR

```bash
curl http://localhost:8090/v1/documents/read \
  -H "Authorization: Bearer $AI_API_KEY" \
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

## Optional MCP and client setup

Build/start with `docker compose --env-file /etc/ai-services/runtime.env -f mcp/compose.yaml up -d --build`.
Gateway and MCP share code from the repository root. Manual builds must use
`docker build -f gateway/Dockerfile .` and `docker build -f mcp/Dockerfile .` from
that root, not an isolated component-directory build context.

See [CLIENTS.md](CLIENTS.md) for the exact supported protocol subset, buffered SSE,
per-client scopes, templates and framework compatibility limits.
