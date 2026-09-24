import json
import os
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


GPU = subprocess.check_output(
    [
        "nvidia-smi",
        "--query-gpu=name,driver_version,memory.total",
        "--format=csv,noheader",
    ],
    text=True,
    timeout=10,
).strip()


class Handler(BaseHTTPRequestHandler):
    server_version = "ai-services-block1-test"

    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"status": "ok", "gpu": GPU})
            return
        self._json(404, {"error": "not found"})
    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            payload = {}

        if self.path == "/v1/chat/completions":
            time.sleep(float(os.getenv("CHAT_DELAY", "0")))
            self._json(
                200,
                {
                    "id": "chatcmpl-block1",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "BLOCK1 GPU OK",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "model": payload.get("model", "qwen3-8b"),
                },
            )
            return
        if self.path == "/v1/embeddings":
            time.sleep(float(os.getenv("EMBED_DELAY", "0")))
            self._json(
                200,
                {
                    "object": "list",
                    "data": [{"embedding": [0.1, 0.2], "index": 0}],
                    "model": payload.get("model", "bge-m3"),
                },
            )
            return

        self._json(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        return


ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
