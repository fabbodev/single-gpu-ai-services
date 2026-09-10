# Upstream projects

This reference implementation composes several independent upstream projects. Their licenses, release cadence, and model terms remain their own.

- llama.cpp — LLM inference server
- Speaches / faster-whisper — speech-to-text service
- Coqui TTS — text-to-speech service
- Hugging Face Text Embeddings Inference — embeddings and reranking
- PaddleOCR / PaddleX — OCR VLM and document pipeline

Before upgrading an upstream image or model, test it on the target GPU and re-run both unit tests and live verification. Container tags such as `latest` are convenient for experimentation but immutable digests are preferable for a controlled production deployment.
