# Component map

| Path | Responsibility |
|---|---|
| `gateway/` | stable public REST API |
| `dispatcher/` | exclusive GPU lease and Docker lifecycle |
| `engines/llm/` | llama.cpp / Qwen reference engine |
| `engines/stt/` | Speaches / faster-whisper reference engine |
| `engines/tts/` | Coqui TTS reference engine contract |
| `engines/embeddings/` | BGE-M3 via TEI |
| `engines/reranker/` | BGE reranker via TEI |
| `engines/ocr/` | PaddleOCR-VL + PaddleX composite service |
| `docs/` | manual installation and operational documentation |
