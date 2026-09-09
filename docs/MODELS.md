# Models and runtime assets

Model weights are intentionally not stored in this repository.

The configuration files describe the model/runtime combination used by the reference deployment. Operators are responsible for obtaining the required assets and complying with each upstream model, runtime, and container-image license.

## Reference model layout

```text
/opt/ai-services/models/
├── llm/
├── stt/
├── tts/
├── ocr/
├── embeddings/
└── reranker/
```

The Compose files assume this layout unless edited.

## LLM

Public model ID:

```text
qwen3-8b
```

Reference model file:

```text
/opt/ai-services/models/llm/Qwen3-8B-Q4_K_M.gguf
```

Engine image:

```text
ghcr.io/ggml-org/llama.cpp:server-cuda
```

Reference settings include a 16,384-token context, one parallel slot, and full GPU offload where possible.

## Speech-to-text

Public model ID:

```text
faster-whisper-large-v3
```

Engine model ID:

```text
Systran/faster-whisper-large-v3
```

Engine image:

```text
ghcr.io/speaches-ai/speaches:latest-cuda
```

Reference cache mount:

```text
/opt/ai-services/models/stt/hf-cache
```

## Text-to-speech

Public model ID:

```text
coqui-es-css10-vits
```

Reference model directory:

```text
/opt/ai-services/models/tts/tts_models--es--css10--vits
```

The reference deployment used a locally built image named:

```text
ai-services/coqui-tts:1.0
```

That private/local image is **not** published by this repository, and the original build recipe was not present in the source snapshot used for publication. The included TTS Compose file is therefore a record of the verified runtime contract, not a self-contained build path. Replace the image with a compatible Coqui TTS image/build of your choice if reproducing the service.

The Gateway expects an HTTP endpoint compatible with:

```text
POST /api/tts?text=...
```

and WAV output.

## Embeddings

Public model ID:

```text
bge-m3
```

Engine image:

```text
ghcr.io/huggingface/text-embeddings-inference:86-1.9
```

Reference model cache snapshot:

```text
/opt/ai-services/models/embeddings/hf-cache/
  models--BAAI--bge-m3/
  snapshots/5617a9f61b028005a4858fdac845db406aefb181
```

The verified model produces 1024-dimensional embeddings.

## Reranker

Public model ID:

```text
bge-reranker-v2-m3
```

Engine image:

```text
ghcr.io/huggingface/text-embeddings-inference:86-1.9
```

Reference model cache snapshot:

```text
/opt/ai-services/models/reranker/hf-cache/
  models--BAAI--bge-reranker-v2-m3/
  snapshots/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e
```

## OCR / document parsing

Public model ID:

```text
paddleocr-vl-1.6
```

Reference model directories:

```text
/opt/ai-services/models/ocr/paddle-data/official_models/PP-DocLayoutV3
/opt/ai-services/models/ocr/paddle-data/official_models/PaddleOCR-VL-1.6
```

OCR uses two cooperating containers:

```text
ai-ocr-vlm
ai-ocr-api
```

Reference images:

```text
ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-genai-vllm-server:latest-nvidia-gpu-offline
ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-vl:latest-nvidia-gpu-offline
```

The VLM backend configuration in this repository was tuned for the tested 10 GB GPU reference deployment:

```yaml
gpu-memory-utilization: 0.60
max-model-len: 16384
max-num-batched-tokens: 8192
api-server-count: 1
```

These values are reference settings, not universal recommendations. Different GPUs and model/runtime versions may require different tuning.

## Pinning and reproducibility

Some reference images use mutable tags such as `latest-cuda` or `latest-nvidia-gpu-offline`. For a production deployment, pin versions or digests after validating a known-good combination.
