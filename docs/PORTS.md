# Ports and network exposure

| Component | Container port | Host exposure in reference config | Purpose |
|---|---:|---|---|
| Gateway | 8090 | `0.0.0.0:8090` | Public project REST API |
| Dispatcher | 8092 | none | Private lifecycle control |
| LLM | 8080 | none | llama.cpp backend |
| STT | 8000 | `127.0.0.1:8000` | Speaches backend/debug |
| TTS | 5002 | `127.0.0.1:5002` | Coqui backend/debug |
| Embeddings | 8080 | none | TEI backend |
| Reranker | 8080 | none | TEI backend |
| OCR VLM | 8080 | none | PaddleOCR VLM backend |
| OCR API | 8080 | none | PaddleX document API |

Container ports can overlap because each container has its own network namespace.

All internal components communicate through the external Docker network `ai-services-internal`.
