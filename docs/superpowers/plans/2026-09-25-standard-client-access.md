# Standard client access implementation plan

> Execute inline with test-driven-development and verification-before-completion.

**Goal:** deliver the approved Phase 5C standard-client and credential lifecycle.
**Architecture:** shared registry core, local admin CLI, Gateway/MCP enforcement,
minimal buffered SSE compatibility, private isolated consumer configuration.
**Tech stack:** Python stdlib, FastAPI, FastMCP, Docker Compose, existing lockfiles.
**Spec:** ../specs/2026-09-25-standard-client-access-design.md

## Global constraints
No model/dispatcher changes; no secrets or host addresses in public Git; existing
keys preserved via explicit migration; canonical deployment maintained; deny by
default on scope/config errors; no automated cloud fallback or outgoing messages.

## Review focus
Atomic rename across container mount boundaries; established MCP session
revocation; concurrent registry writers; token output failures; stream-only clients.

## Task 1: registry and safe local administrator
Files: client_access/{registry,admin}.py, scripts/ai-client,
tests/test_client_registry.py, tests/test_client_cli.py.
Interfaces: TokenStore.from_file(path); authenticate(header, required_scope=None);
RegistryUnavailable; CAPABILITIES; registry validation; CLI --registry PATH.
- [ ] Write and run red tests for reload, fail closed, strict parsing, CLI lifecycle.
- [ ] Implement strict v1/v2 parsing and explicit migration; lock/atomic writes.
- [ ] Prove permissions, output failure safety, concurrent writes, no key disclosure.
- [ ] Run full affected suites and commit.

## Task 2: enforce contract at Gateway and MCP boundaries
Files: gateway/app/{auth,main,chat_stream}.py, mcp/{auth,server}.py,
component auth tests, Dockerfiles/compose, root .dockerignore, CI, fixture.
Interfaces: shared TokenStore; explicit transport + capability permission.
- [ ] Red tests for all denied capabilities before leases and live token replacement.
- [ ] Add boundary enforcement, directory mounts, isolated secret access and scoped models.
- [ ] Red/green buffered SSE tests for text, tools, usage, finish and invalid flags.
- [ ] Full four suites and image build validation; commit.

## Task 3: docs/templates and reproducible operational support
Files: docs/{CLIENTS,AUTH,INSTALL,MCP}.md, examples/clients/*,
private Homelab client inventory, recovery instructions/scripts.
- [ ] Validate template syntax against installed OpenClaw and primary documentation.
- [ ] Record compatibility limits, administration, migration, rotation and recovery.
- [ ] Test generic docs/config invariants, no public secrets; commit.

## Task 4: safe deployment and live acceptance
Files: private operational record and sanitized evidence references.
- [ ] Capture current state and rollback assets; test newly built images before cutover.
- [ ] Migrate registry preserving existing keys; canonical deployment of accepted candidate.
- [ ] Live credential create/disable/enable/rotate/revoke with no container restart.
- [ ] Verify capability restrictions and malformed-registry fail-closed/recovery.
- [ ] Run six real services, MCP tool cycle and actual isolated OpenClaw agent.
- [ ] Final self-review, tests, rollout receipts and private docs.
- [ ] Push, PR, check CI, merge and verify deployed tree matches merged release.

## Execution record

Implementation and acceptance evidence are summarized in `../../PHASE5C_ACCEPTANCE.md`. This original task list describes the plan; the PR merge record and private release pin determine the final integration state.
