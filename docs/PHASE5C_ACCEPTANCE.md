# Phase 5C acceptance: standard clients and credential lifecycle

Date: 2026-09-25. Runtime source validated at
`785f311784af42a46bf83ccade8e0ed21fa33939`; subsequent documentation commits do
not change the validated application code. Deployment-specific locations,
identities, raw evidence and the final release pin belong in the private runbook.

## Accepted scope

One REST Gateway and one Streamable HTTP MCP surface serve multiple client
frameworks without changing GPU engine implementations. The server now supports
per-client key lifecycle, explicit capability scopes and safe hot reload.
Existing key hashes and enabled states were preserved by explicit migration.

No model, Dispatcher protocol, GPU arbitration rule, virtual-machine boot policy,
cloud fallback or outgoing messaging behavior was changed.

## Automated checks

| Suite | Result |
|---|---:|
| Root / registry / CLI / templates / reproducibility | 97 passed |
| Gateway | 66 passed |
| Dispatcher | 40 passed |
| MCP | 18 passed |
| Total | 221 passed |

Red/green tests cover atomic replacement, corrupted/missing registry recovery,
strict schema, duplicate identities, parallel writers, exclusive private key
output, directory traversal, special-file rejection and registry byte limits.
Scope denial is checked before GPU acquisition. Buffered SSE text/tool/usage
format and error cleanup are tested. Shared modules were rebuilt into both app
images and their deployed file hashes matched the source.

## Real acceptance on the deployed stack

The opt-in `tests/integration/phase5c_live_access.py` harness passed:

- limited model discovery and denied REST capability;
- real MCP embedding with 1024 dimensions;
- disable/revoke enforcement inside an established MCP session;
- re-enable and scope-policy reload;
- rotation invalidating the prior key;
- malformed registry returning failure, followed by restored service;
- permanent revocation preventing re-enablement.

Gateway/MCP container identities remained unchanged across those credential
operations. The harness revoked its temporary identities and verified all
unrelated client records were unchanged. Code upgrades, unlike key edits, used
controlled app replacement.

All six real Gateway services passed: LLM, embeddings, rerank, TTS, STT, OCR.
The raw MCP embedding and complete LLM -> MCP embedding -> LLM tool cycle passed.
Locked model files still matched size and SHA-256; all engines returned to idle
with 1 MiB observed idle GPU memory on the reference machine.

## Actual consumer integration

An isolated OpenClaw profile was validated with the installed CLI. The actual
OpenClaw agent used the local Chat Completions provider, called MCP reranking,
received the correct top document index, and resumed with the expected final
answer. Existing agent instances were not reconfigured. No cloud fallback was used.

Hermes and GolemBot/OpenCode are configuration-template deliverables, not claimed
live deployments. The Hermes MCP template works alongside an existing primary
model; the optional local-model template explicitly does not satisfy the current
Hermes full-agent context requirement with the 16K reference Qwen.

## Explicit limitations

Chat SSE is buffered after inference, not real-time token streaming. This is an
OpenAI-compatible subset, not the Responses or Anthropic Messages APIs.
The reference model context remains 16384 tokens. There is no key expiry,
credential-management web console, per-client usage quota, or automatic secret escrow.

Agent displays may truncate a full embedding vector. One OpenClaw embedding call
succeeded but the model guessed an incorrect length from the clipped preview.
Raw MCP independently verified 1024 dimensions; the compact rerank task was used
for semantic agent acceptance. Numerical consumers should use REST/raw MCP, not
ask a language model to count a truncated displayed vector.

Fresh-VM disaster recovery and extended soak tests were not performed by 5C.
Recovery credential generation was tested in isolation and the private recovery
contract was updated for v2 directory mounts and capability policies.

**Phase 5C functional acceptance: PASS within the scope above.**
