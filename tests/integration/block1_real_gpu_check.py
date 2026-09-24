import json
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


GATEWAY = "http://127.0.0.1:8090"


def http_json(method, url, payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            return response.status, json.loads(raw or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        body = json.loads(raw or b"{}")
        return exc.code, body


def gateway_json(method, path, payload=None):
    return http_json(method, GATEWAY + path, payload)
def dispatcher_json(method, path, payload=None):
    command = [
        "sudo", "-n", "docker", "exec", "ai-dispatcher",
        "curl", "-sS", "-w", "\n%{http_code}", "-X", method,
    ]
    if payload is not None:
        command += [
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload),
        ]
    command.append("http://127.0.0.1:8092" + path)
    output = subprocess.check_output(command, text=True, timeout=20)
    body, code = output.rsplit("\n", 1)
    return int(code), json.loads(body or "{}")


def docker_running(name):
    output = subprocess.check_output(
        [
            "sudo", "-n", "docker", "inspect",
            "-f", "{{.State.Running}}", name,
        ],
        text=True,
        timeout=5,
    ).strip()
    return output == "true"


def wait_for(predicate, timeout=15, interval=0.05, message="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError(f"timed out waiting for {message}")
def ready():
    code, body = dispatcher_json("GET", "/ready")
    assert code == 200
    return body


def ready_or_none():
    try:
        return ready()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def lease_state(request_id, epoch):
    query = urllib.parse.urlencode({"epoch": epoch})
    code, body = dispatcher_json(
        "GET",
        f"/leases/{request_id}?{query}",
    )
    assert code == 200, (code, body)
    return body["state"]


def acquire_direct(service, request_id, epoch, wait_timeout):
    code, body = dispatcher_json(
        "POST",
        f"/acquire/{service}",
        {
            "request_id": request_id,
            "epoch": epoch,
            "wait_timeout": wait_timeout,
        },
    )
    assert code in (200, 202), (code, body)
    return body


def release_direct(service, request_id, epoch):
    return dispatcher_json(
        "POST",
        f"/release/{service}",
        {"request_id": request_id, "epoch": epoch},
    )


def cancel_direct(service, request_id, epoch):
    return dispatcher_json(
        "POST",
        f"/cancel/{service}",
        {"request_id": request_id, "epoch": epoch},
    )
def wait_lease(request_id, epoch, expected, timeout=15):
    return wait_for(
        lambda: lease_state(request_id, epoch) == expected,
        timeout=timeout,
        interval=0.05,
        message=f"lease {request_id} -> {expected}",
    )


def test_gateway_exclusive_handoff():
    print("TEST 1: Gateway exclusive handoff with real RTX 3080")
    results = {}
    overlap = []
    monitor_stop = threading.Event()

    def monitor():
        while not monitor_stop.is_set():
            try:
                if docker_running("ai-llm") and docker_running("ai-embeddings"):
                    overlap.append(time.monotonic())
            except Exception:
                pass
            time.sleep(0.03)

    def chat():
        results["chat"] = gateway_json(
            "POST",
            "/v1/chat/completions",
            {
                "model": "qwen3-8b",
                "messages": [{"role": "user", "content": "block1"}],
                "max_tokens": 8,
            },
        )

    def embeddings():
        results["embeddings"] = gateway_json(
            "POST",
            "/v1/embeddings",
            {"model": "bge-m3", "input": "block1"},
        )
    monitor_thread = threading.Thread(target=monitor, daemon=True)
    chat_thread = threading.Thread(target=chat)
    embed_thread = threading.Thread(target=embeddings)
    monitor_thread.start()
    chat_thread.start()

    wait_for(
        lambda: docker_running("ai-llm"),
        message="ai-llm running",
    )
    gpu = subprocess.check_output(
        [
            "sudo", "-n", "docker", "exec", "ai-llm",
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total",
            "--format=csv,noheader",
        ],
        text=True,
        timeout=10,
    ).strip()
    print("  GPU:", gpu)

    embed_thread.start()
    time.sleep(1)
    assert docker_running("ai-llm")
    assert not docker_running("ai-embeddings")

    chat_thread.join(25)
    assert not chat_thread.is_alive()
    wait_for(
        lambda: docker_running("ai-embeddings"),
        message="ai-embeddings running after LLM release",
    )
    embed_thread.join(20)
    assert not embed_thread.is_alive()
    wait_for(
        lambda: not docker_running("ai-llm")
        and not docker_running("ai-embeddings"),
        message="both engines stopped",
    )
    monitor_stop.set()
    monitor_thread.join(1)
    assert overlap == [], f"GPU engines overlapped: {overlap}"
    assert results["chat"][0] == 200, results["chat"]
    assert results["embeddings"][0] == 200, results["embeddings"]
    print("  PASS: no overlap; both returned 200 and stopped")


def test_old_release_identity():
    print("TEST 2: delayed release cannot stop the next same-service owner")
    epoch = ready()["epoch"]
    first = str(uuid.uuid4())
    second = str(uuid.uuid4())

    acquire_direct("llm", first, epoch, 5)
    wait_lease(first, epoch, "active")
    release_direct("llm", first, epoch)
    wait_lease(first, epoch, "released")

    acquire_direct("llm", second, epoch, 5)
    wait_lease(second, epoch, "active")
    code, body = release_direct("llm", first, epoch)
    assert code == 200, (code, body)
    time.sleep(0.3)
    assert docker_running("ai-llm")
    assert lease_state(second, epoch) == "active"

    release_direct("llm", second, epoch)
    wait_lease(second, epoch, "released")
    wait_for(lambda: not docker_running("ai-llm"), message="llm stopped")
    print("  PASS: old release was harmless")
def test_queue_expiry():
    print("TEST 3: queued request expires and never starts")
    epoch = ready()["epoch"]
    owner = str(uuid.uuid4())
    waiting = str(uuid.uuid4())

    acquire_direct("llm", owner, epoch, 5)
    wait_lease(owner, epoch, "active")
    acquire_direct("embeddings", waiting, epoch, 2)

    saw_running = False
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        saw_running = saw_running or docker_running("ai-embeddings")
        state = lease_state(waiting, epoch)
        if state == "expired":
            break
        time.sleep(0.05)
    else:
        raise AssertionError("queued embeddings lease did not expire")

    assert not saw_running
    assert not docker_running("ai-embeddings")
    release_direct("llm", owner, epoch)
    wait_lease(owner, epoch, "released")
    print("  PASS: 2s request-specific queue deadline enforced")


def test_cancelled_queue():
    print("TEST 4: cancelled queued request never starts later")
    epoch = ready()["epoch"]
    owner = str(uuid.uuid4())
    waiting = str(uuid.uuid4())

    acquire_direct("llm", owner, epoch, 5)
    wait_lease(owner, epoch, "active")
    acquire_direct("embeddings", waiting, epoch, 10)
    code, body = cancel_direct("embeddings", waiting, epoch)
    assert code == 200 and body["state"] == "cancelled", (code, body)
    release_direct("llm", owner, epoch)
    wait_lease(owner, epoch, "released")
    time.sleep(0.5)
    assert lease_state(waiting, epoch) == "cancelled"
    assert not docker_running("ai-embeddings")
    print("  PASS: cancel tombstone prevented late start")


def test_restart_reconciliation():
    print("TEST 5: Dispatcher restart reconciles orphan engine")
    first_ready = ready()
    epoch1 = first_ready["epoch"]
    request_id = str(uuid.uuid4())

    acquire_direct("llm", request_id, epoch1, 5)
    wait_lease(request_id, epoch1, "active")
    assert docker_running("ai-llm")

    subprocess.check_call(
        ["sudo", "-n", "docker", "restart", "ai-dispatcher"],
        stdout=subprocess.DEVNULL,
        timeout=20,
    )

    second_ready = wait_for(
        lambda: (lambda r: r if r and r.get("ready") else None)(ready_or_none()),
        timeout=20,
        interval=0.2,
        message="dispatcher ready after restart",
    )
    epoch2 = second_ready["epoch"]
    assert epoch2 != epoch1
    wait_for(
        lambda: not docker_running("ai-llm"),
        timeout=15,
        message="orphan llm stopped by reconcile",
    )
    code, _ = release_direct("llm", request_id, epoch1)
    assert code == 409, code

    next_id = str(uuid.uuid4())
    acquire_direct("embeddings", next_id, epoch2, 5)
    wait_lease(next_id, epoch2, "active")
    release_direct("embeddings", next_id, epoch2)
    wait_lease(next_id, epoch2, "released")
    print("  PASS: new epoch, orphan stopped, old command rejected")


def main():
    print("BLOCK 1 REAL DOCKER/GPU VALIDATION")
    health_code, health = gateway_json("GET", "/health")
    assert health_code == 200, health
    current = ready()
    assert current["ready"] is True
    assert current["protocol"] == 2

    test_gateway_exclusive_handoff()
    test_old_release_identity()
    test_queue_expiry()
    test_cancelled_queue()
    test_restart_reconciliation()

    print("FINAL:")
    print("  ai-llm running:", docker_running("ai-llm"))
    print("  ai-embeddings running:", docker_running("ai-embeddings"))
    print("  dispatcher:", ready())
    print("ALL BLOCK 1 REAL GPU CHECKS PASSED")


if __name__ == "__main__":
    main()
