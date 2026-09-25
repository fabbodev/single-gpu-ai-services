# Block 4 Acceptance Report

**Project:** single-gpu-ai-services  
**Acceptance date:** 2026-09-25  
**Branch:** `hardening/recovery-2026-09-block4`  
**Validated commits:** `4aa0888`, `74483ab`  
**GPU host:** NVIDIA GeForce RTX 3080 10 GB

## Acceptance result

Block 4 is accepted. The deployed single-GPU stack was validated with real inference, real Gateway and MCP traffic, concurrent requests, forced engine failure, dispatcher restart/reconciliation, model-lock verification, component tests, and image rebuilds.

At the end of validation the dispatcher reported `ready=true`, `state=idle`, protocol 2; all GPU engines were stopped; GPU usage was 0% and VRAM idle usage was 1 MiB.

## Real end-to-end validation

| Path / service | Result | Evidence |
| --- | --- | --- |
| Gateway → LLM | PASS | HTTP 200, response `LISTO.` |
| Gateway → Embeddings | PASS | HTTP 200, 1024 dimensions |
| Gateway → Reranker | PASS | HTTP 200, correct ordering |
| Gateway → TTS | PASS | Valid WAV, 104224 frames at 22050 Hz |
| Gateway → STT | PASS | Valid Spanish transcription returned |
| Gateway → OCR | PASS | Expected fixture text recovered |
| MCP → Embeddings | PASS | 1024 dimensions |
| LLM → MCP tool → Embeddings → LLM | PASS | Final response `TOOL CYCLE OK.` |
## Concurrency and GPU exclusivity

Three live requests were submitted almost simultaneously: LLM at +0.000 s, embeddings at +0.051 s, and reranker at +0.101 s. All returned HTTP 200.

Observed completion times were 5.747 s, 10.673 s, and 15.610 s respectively. Across 139 container samples there were zero samples with incompatible GPU engines overlapping. The dispatcher therefore serialized the GPU workload as designed.

## Failure and recovery validation

### Active engine crash

An active LLM lease was established and the `ai-llm` container was deliberately killed while serving a request. The request failed with the expected HTTP 502. The dispatcher recovered to `ready=true, state=idle` in 372 ms and did not leave the GPU leased or occupied.

Result: **PASS — ACTIVE_CRASH_AFTER_PATCH**

### Dispatcher restart and reconciliation

A stray `ai-embeddings` engine was deliberately left running before dispatcher restart. On startup the dispatcher reconciled engine state, stopped the orphaned GPU engine, generated a new epoch, and returned to idle in 11.502 s.

Result: **PASS — RECONCILE_AFTER_PATCH**

## Defect found during acceptance

Acceptance testing exposed two lifecycle weaknesses in the dispatcher:

1. GPU engine shutdown was effectively limited to 10 seconds even when a larger cleanup budget was configured.
2. Startup health polling could continue after an engine had already exited.

Commit `74483ab` corrected both behaviors. Docker stop now receives the full cleanup budget, and health polling fails fast when the target container stops or disappears.
## Automated verification after the fix

- Root/reproducibility tests: **51 passed**
- Gateway tests: **44 passed**
- Dispatcher tests after recovery patch: **40 passed**
- MCP tests: **15 passed**
- Gateway image build: **PASS**
- Dispatcher image build: **PASS**
- MCP image build: **PASS**
- Compose configuration for Gateway, Dispatcher, MCP and all engines: **PASS**
- Locked model size and SHA-256 verification: **PASS**
- `git diff --check`: **PASS**

The running dispatcher image after the recovery patch was:
`sha256:724f51623597c39ac841f307b0a7239702818d2ca3a3fda5f553ab93ca69fef0`

The SHA-256 of `dispatcher/engine_manager.py` in the repository matched the file inside the running dispatcher container.

## Notes

The STT smoke test returned a valid Spanish transcription with a minor recognition error at the beginning (`Colamundo` instead of the expected spoken phrase). This is model accuracy behavior and did not indicate an infrastructure or lifecycle failure.

OCR cold start is substantially slower than the other engines because its service initializes the PaddleOCR/VLLM stack. This was expected and remained within the configured startup budget.

## Final disposition

Block 4 acceptance criteria are satisfied. The single RTX 3080 is correctly shared across the supported inference services, GPU leases are serialized, engines release GPU resources after use, startup and shutdown behavior is deterministic, and the dispatcher recovers from both engine crashes and restart-time orphaned workloads.

**BLOCK 4: ACCEPTED**
