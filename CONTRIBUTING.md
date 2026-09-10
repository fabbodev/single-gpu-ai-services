# Contributing

Keep changes small, reviewable, and compatible with the project's security boundary.

Before proposing a change:

1. run the Gateway and Dispatcher unit tests;
2. do not commit model weights, caches, credentials, private keys, or `.env` files;
3. do not add private network addresses or environment-specific hostnames to examples;
4. keep Docker socket access confined to the Dispatcher;
5. document new public endpoints in `docs/API.md`;
6. document new model files or paths in `docs/MODELS.md`;
7. preserve exclusive GPU lease behavior unless the change intentionally redesigns scheduling.

For GPU-specific changes, state the GPU model and VRAM on which the change was tested.
