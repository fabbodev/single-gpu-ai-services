# Engine definitions

Each subdirectory contains the Docker Compose definition for one logical GPU capability.

The Dispatcher does **not** run `docker compose` during inference. Installation creates each engine container once; runtime then uses `docker start` and `docker stop`.

Typical preparation:

```bash
docker compose -f engines/llm/compose.yaml create
docker compose -f engines/stt/compose.yaml create
docker compose -f engines/tts/compose.yaml create
docker compose -f engines/embeddings/compose.yaml create
docker compose -f engines/reranker/compose.yaml create
docker compose -f engines/ocr/compose.yaml create
```

All containers must join the external Docker network `ai-services-internal` and must keep the container names expected by `dispatcher/engine_manager.py`.

See `../docs/INSTALL.md` for the complete manual sequence and model prerequisites.
