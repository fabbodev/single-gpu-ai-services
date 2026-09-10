# Models

Model weights are not bundled with this repository.

The project separates code from model assets so operators can choose where to obtain models, review licenses independently, and replace models without rewriting the Dispatcher architecture.

## Expected model families

| Capability | Public model id | Reference model family | Expected local location |
|---|---|---|---|
| LLM | `qwen3-8b` | Qwen3-8B GGUF, Q4_K_M reference quantization | `/opt/ai-services/models/llm/Qwen3-8B-Q4_K_M.gguf` |
| STT | `faster-whisper-large-v3` | Systran faster-whisper-large-v3 | `/opt/ai-services/models/stt/hf-cache/` |
| TTS | `coqui-es-css10-vits` | Coqui Spanish CSS10 VITS | `/opt/ai-services/models/tts/tts_models--es--css10--vits/` |
| Embeddings | `bge-m3` | BAAI bge-m3 | `/opt/ai-services/models/embeddings/bge-m3/` |
| Reranker | `bge-reranker-v2-m3` | BAAI bge-reranker-v2-m3 | `/opt/ai-services/models/reranker/bge-reranker-v2-m3/` |
| OCR | `paddleocr-vl-1.6` | PaddleOCR-VL-1.6 + PP-DocLayoutV3 | `/opt/ai-services/models/ocr/paddle-data/official_models/` |

## LLM

The reference compose file expects:

```text
/opt/ai-services/models/llm/Qwen3-8B-Q4_K_M.gguf
```

Inside the container it is mounted read-only at:

```text
/models/Qwen3-8B-Q4_K_M.gguf
```

If you use another filename or model, update both `engines/llm/compose.yaml` and the public model contract in `gateway/app/main.py` as needed.

## STT

The STT engine uses Speaches with a Hugging Face cache mounted at:

```text
/opt/ai-services/models/stt/hf-cache
```

The Gateway exposes the friendly model id `faster-whisper-large-v3` and sends the backend model id `Systran/faster-whisper-large-v3`.

Depending on how you provision Speaches, the model may be downloaded into the mounted cache during an initial preparation step. Do not commit the cache to Git.

## TTS

Expected files:

```text
/opt/ai-services/models/tts/tts_models--es--css10--vits/
├── model_file.pth.tar
└── config.json
```

The verified deployment used a locally built Coqui TTS GPU container. See `docs/INSTALL.md` for the explicit limitation and image contract.

## Embeddings

The public compose file expects a directly mountable BGE-M3 model directory:

```text
/opt/ai-services/models/embeddings/bge-m3
```

This is intentionally more portable than embedding a machine-specific Hugging Face snapshot hash in the compose file.

## Reranker

The public compose file expects:

```text
/opt/ai-services/models/reranker/bge-reranker-v2-m3
```

As with embeddings, the public layout avoids hard-coding a local cache snapshot hash.

## OCR

Expected structure:

```text
/opt/ai-services/models/ocr/paddle-data/official_models/
├── PaddleOCR-VL-1.6/
└── PP-DocLayoutV3/
```

The VLM service reads `PaddleOCR-VL-1.6`; the PaddleX document pipeline also uses `PP-DocLayoutV3` for layout detection.

## Licensing

Each upstream model and container image has its own license and distribution terms. This repository's Apache-2.0 license applies to this project's code and documentation; it does not relicense third-party model weights or container images.
