# FastMCP Tool Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional FastMCP Streamable HTTP adapter for auxiliary GPU tools and make the Qwen chat proxy preserve native tool-calling fields.

**Architecture:** FastMCP is a separate container on the existing internal Docker network. It calls only the Gateway REST API and never touches the Dispatcher or Docker socket directly. Qwen remains the model provider; MCP exposes OCR, STT, TTS, embeddings, and reranking only.

**Tech Stack:** Python 3.12, FastMCP 4.x, httpx, pytest, Docker Compose, existing FastAPI Gateway.

**Spec:** `docs/superpowers/specs/2026-09-10-fastmcp-tools-design.md`

## Global Constraints

- Keep the Gateway REST API as the stable core interface.
- FastMCP must not mount `/var/run/docker.sock` or call the Dispatcher directly.
- Do not expose `/v1/chat/completions` as an MCP tool.
- File-oriented MCP tools use base64 rather than client-local paths.
- Default MCP host publication is loopback-only.
- Preserve the existing acquire/release lifecycle for all GPU requests.

---

### Task 1: Preserve Qwen tool-calling fields

**Files:**
- Modify: `gateway/tests/test_main.py`
- Modify: `gateway/app/main.py`

**Interfaces:**
- Consumes: `POST /v1/chat/completions`
- Produces: transparent forwarding of `tools`, `tool_choice`, and `parallel_tool_calls`

- [ ] Add a test request containing OpenAI-compatible tool definitions and assert the fake llama.cpp client receives those fields unchanged.
- [ ] Run the Gateway test and verify it fails because the current allowlist drops those keys.
- [ ] Extend the chat-completion allowlist with the three tool-calling fields.
- [ ] Run all Gateway tests and verify they pass.

### Task 2: Add the FastMCP proxy tools

**Files:**
- Create: `mcp/server.py`
- Create: `mcp/requirements.txt`
- Create: `mcp/tests/test_server.py`
- Create: `mcp/tests/__init__.py`
- Create: `mcp/tests/conftest.py`

**Interfaces:**
- Consumes: Gateway REST endpoints on `GATEWAY_URL`
- Produces: `read_document`, `transcribe_audio`, `generate_speech`, `embed_text`, `rerank_documents`

- [ ] Write tests for request paths, payload translation, binary/base64 handling, and HTTP errors.
- [ ] Verify tests fail before the proxy implementation exists.
- [ ] Implement a small injectable `GatewayClient` and explicit FastMCP tools.
- [ ] Reject malformed base64 before making HTTP requests.
- [ ] Return TTS WAV data as base64 plus media type.
- [ ] Run all MCP tests.

### Task 3: Containerize the MCP adapter

**Files:**
- Create: `mcp/Dockerfile`
- Create: `mcp/.dockerignore`
- Create: `mcp/compose.yaml`

**Interfaces:**
- Consumes: external Docker network `ai-services-internal`
- Produces: Streamable HTTP MCP endpoint at `/mcp` on container port 8091

- [ ] Build from Python 3.12 slim.
- [ ] Set `GATEWAY_URL=http://ai-gateway:8090`.
- [ ] Publish `${MCP_BIND_ADDRESS:-127.0.0.1}:8091:8091`.
- [ ] Validate Compose configuration and Docker build.

### Task 4: Add CI coverage

**Files:**
- Modify: `.github/workflows/tests.yml`

**Interfaces:**
- Consumes: `mcp/requirements.txt`, MCP tests, Dockerfile and compose file
- Produces: an independent `mcp` CI job plus Compose validation

- [ ] Install MCP requirements under Python 3.12.
- [ ] Run `pytest -q` in `mcp/`.
- [ ] Build the MCP image.
- [ ] Validate `mcp/compose.yaml` in the existing Compose job.

### Task 5: Document agent integration and live verification

**Files:**
- Modify: `docs/MCP.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: MCP endpoint `http://<trusted-host>:8091/mcp`
- Produces: operator instructions for OpenClaw/GolemBot-compatible MCP clients

- [ ] Document that Qwen remains the model provider and MCP contains auxiliary tools only.
- [ ] Document remote-safe base64 file inputs and the loopback/Tailscale binding recommendation.
- [ ] Document live verification sequence: Qwen emits tool call -> LLM lease releases -> tool engine runs -> result returns -> Qwen restarts with tool result.
- [ ] Explicitly distinguish CI verification from GPU live verification.
