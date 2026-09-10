# Testing

The repository contains CPU-only unit tests for the Gateway request lifecycle and Dispatcher/EngineManager orchestration logic. These tests do not download models or require an NVIDIA GPU.

Run Gateway tests:

```bash
cd gateway
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

Run Dispatcher tests:

```bash
cd dispatcher
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

GitHub Actions runs both suites.

GPU integration testing is intentionally separate because it requires model files, large container images, NVIDIA drivers, and a real GPU. Use `docs/VERIFY.md` and `docs/INSTALL.md` for live validation.
