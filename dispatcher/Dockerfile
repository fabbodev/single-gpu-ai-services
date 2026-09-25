FROM docker:cli@sha256:018edbc908e08fcc9dbf029c812c34251e9b4719e6f71ca0e5eae2a987d014ca

RUN apk add --no-cache \
    python3=3.14.7-r1 \
    py3-pip=26.1.2-r0 \
    curl=8.22.0-r0
RUN python3 -m venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt

COPY . .

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8092", "--workers", "1"]
