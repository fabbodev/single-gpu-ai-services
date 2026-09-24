FROM pytorch/pytorch@sha256:417bd75df6365104c283ea4c1651fb3530d9eb5a4c2fafa51943cff2a94e6385

# Keep the digest-frozen Torch/CUDA stack; do not resolve or reinstall it with pip.
RUN python -m venv --system-site-packages /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

WORKDIR /app
COPY build-requirements.lock.txt requirements.lock.txt ./
# Bootstrap the exact sdist build tools first (docopt has no wheel).
RUN pip install --no-cache-dir --no-deps -r build-requirements.lock.txt
# WAV-only Gateway contract: SoundFile's Linux wheel bundles libsndfile.
# No apt/FFmpeg tree and no isolated build environment with floating packages.
RUN pip install --no-cache-dir -r requirements.lock.txt --no-deps --no-build-isolation --only-binary=soundfile
COPY runtime_check.py .
RUN pip check && python runtime_check.py && tts-server --help > /dev/null

STOPSIGNAL SIGINT
ENTRYPOINT ["/opt/venv/bin/tts-server"]
