# Manual install checklist

Use this only as a checklist; the explanations and exact commands live in `INSTALL.md`.

- [ ] NVIDIA driver works: `nvidia-smi`
- [ ] Docker and Compose v2 installed
- [ ] NVIDIA Container Toolkit works inside Docker
- [ ] repository placed at `/opt/ai-services` or compose paths adjusted
- [ ] `ai-services-internal` Docker network created
- [ ] model directories populated
- [ ] compatible Coqui TTS image prepared if TTS is required
- [ ] all engine containers created, not left running
- [ ] Dispatcher built and started
- [ ] Gateway built and started
- [ ] `/health` and `/v1/models` respond
- [ ] each desired engine tested through the Gateway
- [ ] engine containers return to stopped state after requests
- [ ] security guidance reviewed before external exposure
