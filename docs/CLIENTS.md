# Standard client contract

Agent frameworks configure protocols; models do not connect themselves.
A new harness does not require a new GPU service or Dispatcher integration.
Use a private-network address and a dedicated client credential.

| Interface | Address shape | Contract |
|---|---|---|
| REST | `http://HOST:8090/v1` | OpenAI-compatible subset plus explicit extensions |
| MCP | `http://HOST:8091/mcp` | Streamable HTTP tools, Bearer authentication |

| Capability | REST path below `/v1` | MCP tool | Additional scope |
|---|---|---|---|
| Chat | `/chat/completions` | Client runs its own model loop | `llm` |
| Embeddings | `/embeddings` | `embed_text` | `embeddings` |
| Rerank | `/rerank` | `rerank_documents` | `reranker` |
| Documents | `/documents/read` | `read_document` | `ocr` |
| Transcribe | `/audio/transcriptions` | `transcribe_audio` | `stt` |
| Speech | `/audio/speech` | `generate_speech` | `tts` |

All requests require `gateway`; MCP also requires `mcp`. Model discovery is
permission-filtered. The server never treats a transport scope as a wildcard.
See [AUTH.md](AUTH.md) for administration and migration.

## Compatibility boundaries

Chat supports JSON completions, function tool calls, and **buffered SSE** when
`stream=true`. Inference finishes and the lease is released before SSE output is
sent. `X-AI-Stream-Mode: buffered` makes that behavior explicit; there is no
claim of real-time token delivery or an SSE heartbeat while a model cold-starts.

Use an HTTP/request timeout of 600 seconds to accommodate queueing, cold starts,
inference, cleanup and tool orchestration. A queue timeout can still reject work
when the single GPU is busy; clients should use bounded backoff, not retry storms.
The reference LLM has a **16384-token total context**, not a large coding-model
context. Keep prompts, tool schemas and output within that budget.

Reranking and document reading are project-specific extensions. There is no
`/v1/responses`, Anthropic Messages API, image-generation API or generic file/RAG
store. STT accepts multipart audio; TTS returns WAV. BGE-M3 is text embedding,
not a drop-in replacement for Immich's face or visual-search models.

## Framework templates

See `examples/clients/`. Substitute only the deployment address and configure a
private environment variable `AI_SERVICES_API_KEY` from the client's secret file.
Never commit resolved configurations or copy a bootstrap key to multiple clients.

- OpenClaw: custom provider `api: openai-completions`, model
  `ai-services/qwen3-8b`, MCP Streamable HTTP. Validate with the installed
  `openclaw config validate`; prefer an isolated `--profile ai-services` first.
- Hermes: `hermes-mcp.yaml` adds these tools to an existing primary model.
  The optional model template describes the actual 16K server, but is NOT a
  validated full Hermes agent deployment: current Hermes documentation states
  a 64K minimum for agent/tool context. Do not pretend this server has 64K.
- GolemBot: pair `golem.yaml` with `opencode.json` in a separate bot workspace.
  Select OpenCode's Chat Completions adapter. GolemBot's Codex engine expects
  Responses, and its Claude Code engine expects Anthropic Messages; neither
  becomes compatible merely by changing a base URL.

Templates establish the wire contract, not proof that every framework/version has
been deployed. MCP tools can be used while an agent retains another primary LLM;
no cloud fallback or automatic billing behavior is enabled by these examples.

## Adding a consumer

Create a dedicated client ID with the minimum scopes. Deliver its key privately,
configure the two endpoints, test a permitted call and a deliberately denied one,
then check that the GPU returns to idle. Record client owner/purpose in private
operations documentation. Disabling one ID must not affect any other ID.

Model-specific workload quality is separate from protocol compatibility. A small
Qwen model can successfully call tools without being a substitute for a large
reasoning or coding model on every task.

## Primary configuration references (reviewed 2026-09-25)

- [OpenClaw custom providers](https://docs.openclaw.ai/gateway/config-tools/custom-providers)
- OpenClaw's installed `config schema` and `mcp --help` define version-specific fields.
- [Hermes providers and context requirements](https://hermes-agent.nousresearch.com/docs/integrations/providers)
- [Hermes MCP configuration](https://hermes-agent.nousresearch.com/docs/reference/mcp-config-reference)
- [GolemBot provider routing](https://github.com/0xranx/golembot/blob/main/docs/guide/provider-routing.md)
- [OpenCode custom providers](https://opencode.ai/docs/providers/)
- [OpenCode MCP authentication](https://opencode.ai/docs/mcp-servers/)

## Acceptance and large numerical outputs

See [PHASE5C_ACCEPTANCE.md](PHASE5C_ACCEPTANCE.md) for actual tested coverage.
Some agent UIs clip large tool results, including embedding arrays. Use the raw
REST/MCP response for numerical indexing; a model's description of a clipped
preview is not a vector-length assertion.
