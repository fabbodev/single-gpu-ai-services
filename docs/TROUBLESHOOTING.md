# Troubleshooting

## Docker cannot see the GPU

Run:

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi
```

If the first works and the second does not, fix the Docker/NVIDIA Container Toolkit integration before debugging this project.

## Dispatcher health works but an engine never becomes ready

Inspect the target container:

```bash
docker logs ai-llm
docker logs ai-stt
docker logs ai-tts
docker logs ai-embeddings
docker logs ai-reranker
docker logs ai-ocr-vlm
docker logs ai-ocr-api
```

Then check that the model path mounted by that engine exists on the host.

## `docker start` says the container does not exist

Engine containers are created during installation. Re-run the appropriate create command, for example:

```bash
docker compose -f engines/llm/compose.yaml create
```

## Gateway returns HTTP 502

A 502 normally means the Gateway acquired the lease but the backend request failed. Inspect Gateway, Dispatcher, and target-engine logs:

```bash
docker logs ai-gateway
docker logs ai-dispatcher
docker logs <engine-container>
```

## OCR runs out of VRAM on a 10 GB card

Start with the verified settings in `engines/ocr/backend_config.yaml`. Do not increase `gpu-memory-utilization`, context length, or batch-token settings until the baseline works.

## Requests appear serialized

That is intentional. The Dispatcher grants one logical GPU lease at a time. A second GPU-heavy service waits until the current service releases the lease.

## Dispatcher cannot start/stop containers

Confirm that its compose definition mounts:

```text
/var/run/docker.sock:/var/run/docker.sock
```

Remember that this mount is security-sensitive; do not solve permission problems by exposing the Dispatcher publicly.
