# Operating model

The host has two persistent control-plane containers and a set of normally stopped GPU engine containers.

Persistent:

```text
ai-gateway
ai-dispatcher
```

Normally stopped until requested:

```text
ai-llm
ai-stt
ai-tts
ai-embeddings
ai-reranker
ai-ocr-vlm
ai-ocr-api
```

A request to the Gateway causes the appropriate logical engine to acquire the single lease, start, answer, and stop. This is intended for workloads where conserving VRAM is more important than instant warm responses from every model simultaneously.
