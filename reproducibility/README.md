# Block4: preparation and GPU-host handoff

## Status and boundaries

This is the **CPU preparation checkpoint**, based on Block3 `5090151`, on the
accumulative `hardening/recovery-2026-09-block4` branch. It is not a GPU acceptance
report. Commit and push this preparation checkpoint to Block4 for Git-based
transfer to the GPU host. Further validation/fix commits continue on that branch.
No merge, deployment, or changes to the stable control plane are part of this handoff.

The architecture remains `MCP -> Gateway -> Dispatcher -> engines`. Only the
Dispatcher service mounts the Docker socket. One logical GPU service at a time;
OCR's two containers form one logical service. Host-side administrative scripts
use the local Docker CLI; they do not create another socket-enabled service.

All heavy work belongs on **ai-services**, not agent-hub: image pulls, TTS builds,
model downloads, CUDA checks, and inference. Preparation uses source/metadata and
small synthetic test fixtures only. All real validation below is still pending.

## Files and offline checks

| File | Purpose |
|---|---|
| `images.lock.json` | Exact registry digests and amd64 child identities |
| `models.lock.json` | Exact source revisions, paths, sizes, SHA-256 |
| `image-sizes.metadata.json` | Metadata-only size inventory from 2026-09-24 |
| `provision_models.py` | Explicit, selected-model download and verification |
| `verify_models.py` | Offline size/hash/reference verification |
| `image_inventory.py` | Registry metadata inspection; never pulls layers |
| `ai_services_tools.py` | Native GPU-host preflight, one-image pull, image receipts, TTS build and idle checks |
| `run_cpu_checks.py` | All CPU suites, isolated by component |
| `../engines/tts/` | New Coqui runtime recipe, exact dependencies, ABI guards |
| `../tests/integration/block4_real_gpu_check.py` | Opt-in real Gateway/MCP/LLM-cycle smoke checks |

From the repository root, using a development interpreter that has the component
test dependencies already installed:

```sh
python reproducibility/run_cpu_checks.py --log-dir /tmp/block4-cpu-evidence
python3 reproducibility/provision_models.py --check-only --offline --model llm
python3 reproducibility/ai_services_tools.py
python3 tests/integration/block4_real_gpu_check.py --service tool-cycle
```

The latter three commands are offline plans/checks. They do not read client
secrets, pull images, or download model payloads. The full CPU runner executes
root preparation tests, Dispatcher, Gateway, and MCP in separate Python processes.
A bare `pytest` across the monorepo has a pre-existing `tests.conftest` import-name
collision; do not mistake that invocation problem for an application regression.
The existing development environment is not a rebuilt production image.

To repeat metadata-only registry inspection, explicitly opt in:

```sh
python3 reproducibility/image_inventory.py --inspect-registry --output /tmp/block4-image-metadata.json
```

## Space planning

Registry manifests/configs were inspected, amd64 identity was checked, and
compressed layers were deduplicated by digest. No layer download was performed.

| Image | Compressed GiB |
|---|---:|
| Dispatcher base | 0.062 |
| Python base | 0.040 |
| llama.cpp | 2.412 |
| Speaches | 2.711 |
| TEI embeddings / reranker, shared image | 2.929 |
| OCR VLM | 6.833 |
| OCR API | 5.908 |
| PyTorch TTS base | 3.994 |
| **All unique compressed layers** | **24.538** |

Locked model files total **14,878,284,383 bytes (13.856 GiB)**. Their sizes are
from the manifest, not a report of local downloads. These numbers **do not prove
that disk space is sufficient**: expanded image layers, build caches, temporary
ZIPs and HF caches add to the footprint. Measure the Docker and model filesystems
on ai-services before and after each large operation. Do not run automatic prune.

## Move the candidate without deploying it

Retrieve the published Block4 branch with Git in a **new staging directory
outside `/opt/ai-services`**. Clone the repository with
`--single-branch --branch hardening/recovery-2026-09-block4`; verify that
`git rev-parse HEAD` matches the preparation checkpoint reported in the handover
and that `git status --short` is empty before image pulls or builds.

Do not pull or switch branches in the stable deployment. A clone destination
must be new rather than overwritten. The source-only archive from the previous
handoff is an older pre-commit fallback, not the canonical transfer method.
Deployment-local addresses and secrets remain outside the public repository.

**A separate directory is not a separate Docker deployment.** Existing Compose
files use canonical `container_name` values, ports, and the shared external
network. Do NOT `compose up` a second control plane from staging; that can collide
with the stable deployment and create a second authority over the GPU.

For initial real-engine checks, the existing stable control plane may remain the
sole authority after its current state is verified. Before creating any canonical
engine container, inspect whether it already exists and who owns it. Never remove,
replace, force-recreate or manually start/stop it blindly. If a stable container,
network, service or `/opt/ai-services` must change, identify the exact impact and
obtain operational approval first. A later controlled control-plane build/test or
cutover is a separate gate, not performed automatically by this toolkit.

## Native ai-services preflight and one-image pulls

All commands in the remaining sections are **future GPU-host steps, not commands
that have already run**. `ai_services_tools.py` checks the native hostname, local
Unix-socket Docker context, and daemon hostname, and requires `--execute`.
It fails closed on agent-hub; it is intended to run natively, not inside a helper
container or against a remote Docker context.

```sh
python3 reproducibility/ai_services_tools.py --action preflight --execute --receipt /tmp/block4-preflight.json
python3 reproducibility/ai_services_tools.py --action idle --execute
python3 reproducibility/ai_services_tools.py --action pull --image llm --execute --receipt /tmp/block4-llm-image.json
python3 reproducibility/ai_services_tools.py --action verify-images --image llm --execute
```

Repeat pulls individually for `embeddings`, `stt`, `tts_base`, `ocr_vlm`, `ocr_api`,
and required control-plane/provisioner bases. TEI is shared with `reranker`.
Each pull records a local image ID, matching RepoDigests and linux/amd64 identity.
No helper starts/stops an engine or prunes images. No bulk pull action exists.
If a digest, platform, disk check or registry request fails, stop at that gate;
do not silently update the lock or switch to a floating tag.

## New TTS recipe: build only on the GPU host

The lost `ai-services/coqui-tts:1.0` image is not claimed to have been rebuilt.
The new candidate is `ai-services/coqui-tts:0.27.5-cu128`, based on the pinned
PyTorch 2.8.0 / CUDA 12.8 image. It has 83 exact non-CUDA Python pins, with their
Python 3.11/Linux dependency metadata recorded in `dependencies.metadata.json`.
Torch/torchaudio and the NVIDIA stack are inherited from the base digest rather
than re-resolved by pip. Metadata closure is not proof of build/import/ABI success.

The build disables dependency resolution and isolated floating build requirements,
then runs `pip check`, Python/Torch/torchaudio/CUDA/Coqui version guards,
`TTS.api` and SoundFile imports, and `tts-server --help`. Actual GPU visibility is
an additional runtime check, not asserted during a GPU-less Docker build.

This recipe serves the existing **WAV-only Gateway contract**. It uses SoundFile's
Linux binary wheel rather than adding an apt/FFmpeg dependency tree. No arbitrary
codec support is promised. Source references used for this choice:

- https://raw.githubusercontent.com/idiap/coqui-ai-TTS/v0.27.5/TTS/server/server.py
- https://github.com/pytorch/pytorch/blob/v2.8.0/Dockerfile
- https://python-soundfile.readthedocs.io/en/latest/#installation
- Exact package metadata URLs are recorded in `dependencies.metadata.json`.

After verifying the pinned base is present locally:

```sh
python3 reproducibility/ai_services_tools.py --action build-tts --execute --receipt /tmp/block4-tts-build.json
```

The build receipt records the local image ID; the local tag alone is not an
immutable release identity. Record/reuse that ID during acceptance. With all GPU
engines stopped and the Dispatcher idle, a one-shot GPU visibility probe may run:

```sh
docker run --rm --pull=never --gpus all --network none --entrypoint python \
  ai-services/coqui-tts:0.27.5-cu128 /app/runtime_check.py --require-gpu
python3 reproducibility/ai_services_tools.py --action idle --execute
```

This one-shot check loads no model and does not prove CSS10 inference. Then test
the exact locked CSS10 model through the normal Gateway/Dispatcher route. Any
fix belongs in the source recipe/lock, not in a manually modified container.

## Provision one model, verify it, then exercise it

The provisioner now requires **`--download` or `--check-only`**. An invocation
without either mode is rejected before accessing the network. `--model` filters
both downloads AND final verification; it no longer fails on unrelated missing
models. `--model` can be repeated; omitting it selects all groups, so use it in
this progressive validation phase.

Build the provisioner only on ai-services after its Python base is pulled:

```sh
docker build --platform linux/amd64 --pull=false -t ai-services/model-provisioner:block4 reproducibility
```

After checking/creating the canonical model directory with appropriate ownership
and sufficient space, the following example provisions **only Qwen**:

```sh
docker run --rm --pull=never \
  --mount type=bind,src=/opt/ai-services/models,dst=/models \
  ai-services/model-provisioner:block4 --download --model llm
python3 reproducibility/verify_models.py --root /opt/ai-services/models --model llm
```

Use `--mount` so a mistyped missing host directory fails instead of silently being
created by Docker. Preserve model-directory/cache ownership required by each
runtime, particularly the non-root STT image; inspect its user after pull rather
than guessing a numeric UID or using world-writable permissions. Model files can
be written as an explicitly chosen numeric user when ownership requires it.
Never loosen `/etc/ai-services` secret permissions.

HF downloads can be anonymous or use `HF_TOKEN_FILE` mounted read-only into the
provisioner. Never print the token, put it in the repository/archive, pass its
value on a command line, or change canonical bot-token permissions. The client
Bearer and Dispatcher internal token are separate and must stay that way.

Order: **llm -> embeddings -> reranker -> stt -> tts -> ocr**. At each step:
locked download -> exact size/SHA-256 -> reviewed engine container creation ->
real Gateway inference -> clean Dispatcher release/stop -> GPU idle. STT uses
its exact HF cache snapshot and `refs/main` revision; TTS verifies the archive
and each allowlisted extracted file. Corruption fails closed; inspect before any
repair or deletion. After all groups exist, run the verifier without `--model`.

## Real smoke tests and evidence gates

The prepared smoke harness is inert by default. Once canonical engines have been
created under the existing lifecycle contract and a single control plane owns
them, use a protected client token file with suitable scopes. Set non-secret
`GATEWAY_URL`, `MCP_URL`, and `BOT_TOKEN_FILE` paths locally, never in tracked files.
For native MCP checks, use a separate validation venv populated from the MCP
lockfile; do not modify system Python. Root-readable bootstrap tokens may need
an explicitly privileged test invocation; never chmod them for convenience.

```sh
python3 tests/integration/block4_real_gpu_check.py --service llm \
  --base-url "$GATEWAY_URL" --token-file "$BOT_TOKEN_FILE" --execute
python3 tests/integration/block4_real_gpu_check.py --service tts \
  --base-url "$GATEWAY_URL" --token-file "$BOT_TOKEN_FILE" --wav-output /tmp/block4-speech.wav --execute
python3 tests/integration/block4_real_gpu_check.py --service stt \
  --base-url "$GATEWAY_URL" --token-file "$BOT_TOKEN_FILE" --file /tmp/block4-speech.wav --expect-text Hola --execute
python3 tests/integration/block4_real_gpu_check.py --service ocr \
  --base-url "$GATEWAY_URL" --token-file "$BOT_TOKEN_FILE" --file /path/to/known-fixture.png --expect-text EXPECTED --execute
```

Run `embeddings` and `reranker` the same way without a file. Repeat OCR with a
known small PDF separately; image success is not PDF success. No real audio or
OCR fixture was provisioned on agent-hub. The TTS-to-STT round trip is available
only after TTS is validated; a known existing audio fixture lets STT run earlier.

For MCP and then the full client-orchestrated tool cycle:

```sh
python tests/integration/block4_real_gpu_check.py --service mcp-embeddings \
  --base-url "$GATEWAY_URL" --mcp-url "$MCP_URL" --token-file "$BOT_TOKEN_FILE" --execute
python tests/integration/block4_real_gpu_check.py --service tool-cycle \
  --base-url "$GATEWAY_URL" --mcp-url "$MCP_URL" --token-file "$BOT_TOKEN_FILE" --execute
```

The cycle is Qwen tool call -> release/idle -> MCP embed_text -> release/idle ->
Qwen resume. This harness is a client, not a new orchestrator service or change to
the architecture. It checks nonempty responses, finite vectors/ranking, valid WAV
frames, and engine shutdown/VRAM idle. It does not establish model quality by itself.

For **GPU acceptance**, also record image IDs, actual GPU process/memory activity
during each inference, CUDA visibility, Docker GPU device requests, stop signals,
exit status/OOMKilled flags, and Dispatcher lifecycle logs. A successful HTTP
response alone does not prove GPU execution or absence of transient overlap.
Specifically validate STT `WHISPER__TTL=0`, STT/TTS `SIGINT` without forced kill,
and no simultaneous different logical GPU services. Preserve redacted evidence;
do not log tokens. Existing Block3 synthetic E2E scripts are not substitutes:
for example their hard-coded synthetic embedding vector is not a real-model test.

## Completion still required on ai-services

Rebuild and run tests inside the exact control-plane images, provision/hash real
models, validate all six engines on the RTX3080, verify cleanup and single-service
scheduling, and run real MCP/tool-cycle checks. Any controlled stable-deployment
change needs its own reviewed impact/rollback step. Only after those gates pass
can full Etapa4 receive its final GPU acceptance commit. Intermediate preparation
and fix commits/pushes on Block4 are allowed; no merge is part of this handoff.

Package versions and base/model digests are pinned, but this preparation does not
claim byte-for-byte reproducible built image output, PyPI artifact mirroring, or
indefinite upstream artifact availability. Those are distinct guarantees.
