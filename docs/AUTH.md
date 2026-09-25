# Client identity, scopes, and live credential administration

Gateway and MCP require Bearer credentials in addition to private-network access.
Use a different identity for each application/instance, not one shared human key.
The standard-library-only `client_access` module is shared by both services.

## Registry and secret separation

- `/etc/ai-services/clients/client-tokens.json`: version 2 client registry.
- `/etc/ai-services/clients/`: root-owned 0700 directory, file mode 0400.
- Gateway/MCP mount this directory read-only at `/run/ai-clients`.
- `/etc/ai-services/secrets/dispatcher-token`: separate internal secret, mounted
  only into Gateway and Dispatcher. Never give this secret to clients or MCP.
- Plaintext client keys belong in the client's secret store or an operator-only
  delivery directory, never in Git or the mounted client-registry directory.

Directory mounting is required: replacing an individually bind-mounted file can
leave a container reading the old inode after an atomic registry update.

## Permissions

Every API request needs `gateway`; MCP also needs `mcp` because it forwards the
same Bearer token to Gateway. Each inference request additionally needs one of
`llm`, `embeddings`, `reranker`, `ocr`, `stt`, or `tts`. Transport permissions alone
never grant inference. `/v1/models` lists only authorized capabilities.

An embedding-only indexer can have `gateway,embeddings`. An agent using MCP
embedding tools needs `gateway,mcp,embeddings`; add only other required capabilities.

## Local administrator

Run as the registry owner (root in production). There is no network admin API.
The executable can be symlinked from `/usr/local/bin/ai-client` to
`/opt/ai-services/scripts/ai-client`. It requires Python 3 on Linux, not pip.

```bash
ai-client init
ai-client create example-agent --scopes gateway,mcp,llm,embeddings \
  --owner operator --purpose assistant \
  --token-file /etc/ai-services/admin/example-agent-token
ai-client list
ai-client disable example-agent
ai-client enable example-agent
ai-client set-scopes example-agent --scopes gateway,mcp,llm,embeddings,reranker
ai-client rotate example-agent --token-file /etc/ai-services/admin/example-agent-next
ai-client revoke example-agent
```

`--token-file` must name a NEW absolute file outside the registry directory.
Its parent must be private and operator-owned. Keys are generated with 256 bits of
randomness and written mode 0400; neither stdout nor the registry contains them.
The server stores only SHA-256 digests. `list` omits even these digests.

A client may instead mint a secure key locally and send only its digest:
`ai-client create example-agent --scopes gateway,llm --token-sha256 DIGEST`.
Use a cryptographic random token; a password is not an adequate API key.

## Rotation and reload behavior

`disable` is reversible; `revoke` is permanent for that client ID. `rotate`
invalidates the previous key; there is no grace period. Update the client's
secret file and restart/reload that client if it caches credentials. Create a
second client ID for a controlled overlap, then revoke the old one.

Writers use a lock and atomic file replacement. Readers check file identity and
modification metadata on each authorization. Missing, malformed, oversized,
ambiguous, or symlinked registries fail closed rather than retaining old access.
Repairing the registry permits later requests without a service restart.
MCP tool calls revalidate authorization even within an established session.
Already admitted inference is allowed to finish; revocation does not kill it.

REST returns 401 for an invalid key, 403 for missing scope, and 503 when the
registry cannot be used. Health remains public; Gateway readiness includes
registry availability. MCP authentication may return an auth failure when its
registry is unavailable. No plaintext credentials are logged by this code.

## Upgrade from the old version 1 registry

Back up the old file securely, then explicitly migrate into the new directory:

```bash
ai-client migrate --from-file /etc/ai-services/secrets/client-tokens.json
```

The default destination is `/etc/ai-services/clients/client-tokens.json`.
Migration refuses overwrite and preserves token hashes and enabled state.
Transport-only v1 entries receive explicit grants for all six capabilities to
preserve their previous behavior. Existing explicit capability policies are not
expanded. Review `ai-client list` immediately after migration.

Deploy the new Gateway/MCP code and directory mounts once. A deployment upgrade
requires a controlled restart; subsequent credential edits do NOT restart them.
Keep the old registry and old images for rollback until acceptance succeeds.
Do not move the Dispatcher token into the shared registry directory.

For a new installation, use `init` then `create`, rather than legacy migration.
For full credential loss, generate new keys and update consumers. Git provides
code and policy examples, not a backup of plaintext keys.

The CLI refuses duplicate IDs/digests, unknown scopes, symlinks, insecure delivery
paths, existing token files and re-enabling revoked identities. A filesystem
failure during registry replacement may leave an unused, protected delivery key;
check the exit status and registry before distributing it. Retrying requires a
fresh delivery filename. No automatic token expiry or key escrow is implemented.
