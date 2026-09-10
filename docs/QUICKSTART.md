# Quick start

This page intentionally does not collapse installation into a script.

For a new RTX 3080 host, follow `INSTALL.md` from top to bottom. The minimum sequence is:

```text
verify NVIDIA -> verify Docker GPU access -> clone repo -> create Docker network
-> place model files -> create engine containers -> start Dispatcher -> start Gateway
-> test each service -> verify engines stop at idle
```

Use this file as an orientation map, not as a replacement for the manual installation guide.
