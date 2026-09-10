from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def _output_ids(payload: dict[str, Any]) -> list[int]:
    sampling = payload.get("sampling_params", {})
    count = int(sampling.get("max_new_tokens", 1))
    source = json.dumps(payload.get("input_ids", []), separators=(",", ":")).encode()
    seed = int.from_bytes(hashlib.sha256(source).digest()[:8], "big")
    return [128 + ((seed + index * 7919) % 100_000) for index in range(count)]


class Handler(BaseHTTPRequestHandler):
    server_version = "AtlasS004Fake/1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _object(self, value: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health_generate":
            self._object({"status": "ok"})
        elif self.path == "/server_info":
            self._object(
                {
                    "version": "s004-fake",
                    "max_total_num_tokens": 1_000_000,
                    "internal_states": [
                        {
                            "memory_usage": {
                                "weight": 1.0,
                                "kvcache": 1.0,
                                "token_capacity": 1_000_000,
                                "startup_available": 1.0,
                                "graph": {},
                            },
                            "running_requests": 0,
                            "waiting_requests": 0,
                        }
                    ],
                    "atlas_fake_treatment": os.environ.get("ATLAS_S004_CONDITION", "device"),
                }
            )
        elif self.path.startswith("/v1/loads"):
            self._object(
                {
                    "timestamp": "2026-09-10T00:00:00Z",
                    "version": "s004-fake",
                    "loads": [
                        {
                            "dp_rank": 0,
                            "num_running_reqs": 0,
                            "num_waiting_reqs": 0,
                            "num_used_tokens": 0,
                            "num_total_tokens": 0,
                            "max_total_num_tokens": 1_000_000,
                            "token_usage": 0.0,
                            "cache_hit_rate": 0.0,
                        }
                    ],
                }
            )
        else:
            self._object({"error": "not found"}, 404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if self.path.startswith("/flush_cache"):
            body = b"Cache flushed.\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path != "/generate":
            self._object({"error": "not found"}, 404)
            return
        output_ids = _output_ids(payload)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for index in range(len(output_ids)):
            chunk = {
                "text": "",
                "output_ids": output_ids[: index + 1],
                "meta_info": {
                    "completion_tokens": index + 1,
                    "queue_time": 0.0,
                    "cached_tokens": 0,
                    "finish_reason": (
                        {"type": "length", "length": len(output_ids)}
                        if index + 1 == len(output_ids)
                        else None
                    ),
                },
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
            time.sleep(0.0001)
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=30000)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
