# Single-GPU assumption

The current Dispatcher models the entire accelerator as one exclusive logical resource. It does not distinguish multiple GPUs or partition one GPU by VRAM budget.

To adapt the project to multiple GPUs, treat that as a scheduling redesign rather than simply changing `gpus: all`: ownership, engine placement, health, and release semantics would all need to become GPU-aware.
