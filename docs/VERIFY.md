# Verification checklist

Use this after installation or after changing an engine definition.

## Host

```bash
nvidia-smi
docker --version
docker compose version
docker network inspect ai-services-internal >/dev/null
```

## Containers exist

```bash
for c in ai-llm ai-stt ai-tts ai-embeddings ai-reranker ai-ocr-vlm ai-ocr-api ai-dispatcher ai-gateway; do
  docker inspect "$c" >/dev/null || echo "missing: $c"
done
```

## Dispatcher is private

The reference `dispatcher/compose.yaml` must not publish a host port. It may mount `/var/run/docker.sock`; the Gateway must not.

## Gateway health

```bash
curl -fsS http://localhost:8090/health
curl -fsS http://localhost:8090/v1/models
```

## Unit tests

Gateway:

```bash
cd /opt/ai-services/gateway
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

Dispatcher:

```bash
cd /opt/ai-services/dispatcher
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

## Idle state

After API calls complete, GPU engines should normally be stopped:

```bash
for c in ai-llm ai-stt ai-tts ai-embeddings ai-reranker ai-ocr-vlm ai-ocr-api; do
  printf '%-18s ' "$c"
  docker inspect -f '{{.State.Running}}' "$c"
done
```

## Privacy scan before public release

From the repository root, inspect any hits before publishing:

```bash
grep -RInE \
  '100\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.|10\.[0-9]+\.|tailscale|proxmox|vmid|/home/[^/ ]+' \
  --exclude-dir=.git . || true
```

Also search for credentials and private keys with your preferred secret scanner. A zero-hit grep is not proof that a repository contains no secrets.
