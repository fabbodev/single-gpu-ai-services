# Phase 5C: standard client access

## Approved outcome
One Gateway REST contract and one MCP tool contract for different agent harnesses.
Per-client credentials, explicit capability scopes, local administration, and safe
hot reload. No change to engines, model weights or GPU arbitration. No cloud
fallback spending or external messaging is enabled by this slice.

## Design
- Shared stdlib-only `client_access` package: strict registry schema, hot-reloading
  token store, atomic/locked local CLI. Gateway and MCP share that implementation.
- Registry v2 keeps SHA-256 token digests, IDs, explicit scopes, enabled status and
  administrative timestamps. Six capability scopes: llm, embeddings, reranker,
  ocr, stt, tts; transports: gateway, mcp. MCP also needs gateway scope.
- No implicit capability grants. Explicit CLI migration expands existing v1
  transport-only entries to preserve existing access without changing their keys.
- New dedicated registry directory `/etc/ai-services/clients/` is mounted read-only
  into Gateway/MCP. Do not mount the dispatcher-secret directory into MCP.
  Directory mounts permit atomic file replacement to become visible to readers.
- Each authentication checks file identity/mtime/ctime/size. Invalid or missing
  current registry fails closed, never retains stale authorizations; repaired files
  are loaded on a subsequent request. In-flight work may finish after revocation.
- MCP tool entry points revalidate token and capability on every call, including
  established sessions. Gateway is also an independent enforcement boundary.
- CLI commands: init, migrate, create, list, rotate, disable, enable, revoke,
  set-scopes. Atomic writes + flock; generated keys go to an exclusive 0400 file
  outside the mounted registry directory. No token printed by default. Revoked
  IDs are tombstones and cannot be re-enabled. Unknown scopes are rejected.
- Existing chat/embeddings/audio endpoints are an OpenAI-compatible subset;
  rerank/OCR are documented extensions, not universal OpenAI endpoints. Chat gains
  buffered SSE (after inference, not real-time token streaming), including tool
  calls, finish reason, optional usage and [DONE]. This retains bounded inference
  and existing lease cleanup while satisfying streaming-only clients.
- REST 401 for invalid keys, 403 for insufficient permissions, 503 for unavailable
  registry. Discovery lists only permitted models. No network admin endpoint.
- Generic config templates for OpenClaw, Hermes, and GolemBot via OpenCode. Codex
  chat-provider integration is not claimed: this server has no Responses endpoint.

## Delivery / safety
Public code contains no deployment IPs, personal profiles, credentials or raw
production logs. Private inventory and rollout report belong in Homelab.
Use isolated worktrees; keep pre-change images/config for rollback. Deploy to the
canonical root only after tests; preserve dispatcher secret and model files.
Existing OpenClaw profiles are not overwritten. A named isolated profile provides
real OpenClaw verification; Hermes/GolemBot templates are not claimed as live
installations. No engine/VM autostart policy is changed.

## Acceptance
Unit and integration tests cover unknown/duplicate/malformed schema, atomic
reload, revocation/rotation, missing/corrupt registry and restoration, scope denial
before acquiring GPU, concurrent writers, exclusive token output, JSON and SSE
chat/tool responses. Real deployment checks use unchanged container IDs during
credential edits, limited clients, MCP sessions, OpenClaw, six real capabilities,
GPU idle after workloads, private/public documentation, commit/push/merge.
