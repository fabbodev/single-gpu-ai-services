import argparse
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request


TEST_TOKEN = "test-bot-token-not-a-real-secret"


def request(base, path, *, token=None, payload=None):
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    method = "GET"
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
        method = "POST"
    req = urllib.request.Request(
        base + path,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()
def docker_running(name):
    output = subprocess.check_output(
        [
            "sudo",
            "-n",
            "docker",
            "inspect",
            "-f",
            "{{.State.Running}}",
            name,
        ],
        text=True,
        timeout=5,
    ).strip()
    return output == "true"


def wait_stopped(name, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not docker_running(name):
            return
        time.sleep(0.1)
    raise AssertionError(f"{name} did not stop")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--token-file")
    args = parser.parse_args()
    token = TEST_TOKEN if not args.token_file else Path(args.token_file).read_text().strip()
    base = f"http://{args.host}:8090"

    code, body = request(base, "/health")
    assert code == 200, (code, body)
    print("health", code)

    code, body = request(base, "/ready")
    assert code == 200 and json.loads(body)["ready"] is True, (code, body)
    print("ready", code)
    code, _ = request(base, "/v1/models")
    assert code == 401, code
    print("models missing token", code)

    code, _ = request(base, "/v1/models", token="wrong-token")
    assert code == 401, code
    print("models wrong token", code)

    code, _ = request(base, "/v1/models", token=token)
    assert code == 200, code
    print("models valid token", code)

    code, body = request(
        base,
        "/v1/chat/completions",
        token=token,
        payload={
            "model": "qwen3-8b",
            "messages": [
                {"role": "user", "content": "block3 security test"}
            ],
            "max_tokens": 8,
        },
    )
    assert code == 200, (code, body)
    parsed = json.loads(body)
    assert parsed["choices"][0]["message"]["content"] == "BLOCK1 GPU OK"
    wait_stopped("ai-llm")
    print("authenticated Gateway -> Dispatcher -> RTX3080 engine PASS")


if __name__ == "__main__":
    main()
