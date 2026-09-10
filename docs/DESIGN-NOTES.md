# Design invariants

These are the assumptions that make the reference implementation easy to reason about:

1. one logical GPU lease exists at a time;
2. the Gateway never controls Docker directly;
3. only the Dispatcher mounts the Docker socket;
4. engine containers are created during installation and started/stopped at runtime;
5. model weights stay outside Git;
6. OCR is one logical lease even though it uses two containers;
7. composite services start in dependency order and stop in reverse order;
8. a Gateway route releases its lease in `finally` after successful acquisition;
9. MCP, authentication, TLS, and reverse-proxy policy remain outside the GPU scheduling core.
