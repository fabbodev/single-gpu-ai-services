# Reproducibility boundaries

The project separates what is reproduced by this repository from what comes from the host and upstream model providers.

## Reproduced here

- Gateway source and container build
- Dispatcher source and container build
- engine container definitions
- exclusive logical GPU lease behavior
- OCR composite lifecycle configuration
- public REST contracts
- manual installation sequence
- CPU-only orchestration tests

## Supplied by the operator

- NVIDIA driver
- Docker Engine / Compose
- NVIDIA Container Toolkit
- model weights
- sufficient disk and VRAM
- a compatible Coqui TTS GPU image if TTS is enabled
- authentication/TLS/reverse proxy if exposed beyond a trusted network

## Upstream variability

Some engine definitions rely on upstream container images. A future upstream image can change behavior even when this repository does not. For repeatable production installs, test and pin image digests after validating them on your hardware.
