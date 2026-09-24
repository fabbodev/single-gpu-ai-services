FROM nvidia/cuda:12.8.1-base-ubuntu24.04

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*

COPY server.py /server.py

CMD ["python3", "/server.py"]
