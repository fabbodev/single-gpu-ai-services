# Installation notes

The installation root `/opt/ai-services` is a convention used by the reference compose files, not a security requirement. If you choose a different path, update host-side volume paths consistently.

The Docker network name `ai-services-internal` and container names are part of the current Dispatcher contract. If you rename them, update `dispatcher/engine_manager.py` and the corresponding Gateway/backend URLs together.
