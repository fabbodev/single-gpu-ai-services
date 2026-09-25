FROM python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9

WORKDIR /app

COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt

COPY models.lock.json .
COPY provision_models.py .
COPY verify_models.py .

ENV HF_HUB_DISABLE_TELEMETRY=1
ENV HF_XET_HIGH_PERFORMANCE=1

ENTRYPOINT ["python", "/app/provision_models.py"]
