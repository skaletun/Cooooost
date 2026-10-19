"""Local OpenAI/Anthropic JSON passthrough with explicit exact-response opt-in.

No request mutation, no dynamic tool replay, no remote telemetry, no automatic
model switching. Native provider prefix caching remains provider controlled.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import urllib.error
import urllib.request
import urllib.parse

from .cache import Cache, eligible, request_key, extract_usage
from .core import root_of

MAX_REQUEST = 8 * 1024 * 1024
MAX_RESPONSE = 24 * 1024 * 1024
PATHS = {"/v1/chat/completions": "openai", "/v1/responses": "openai", "/v1/messages": "anthropic"}


def make_handler(cache: Cache, upstreams: dict[str, str], timeout: int = 90):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Cooooost/1.0"

        def log_message(self, format, *args):
            # Requests may contain confidential content: no URLs or headers in logs.
            return

        def _json(self, status, obj, headers=None):
            raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == "/health":
                return self._json(200, {"status": "ok", "service": "cooooost"})
            if self.path == "/metrics":
                return self._json(200, cache.stats())
            return self._json(404, {"error": "not_found"})

        def do_POST(self):
            provider = PATHS.get(self.path)
            if provider is None:
                return self._json(404, {"error": "unsupported_endpoint"})
            size = self.headers.get("Content-Length")
            if not size or not size.isdigit() or not 0 < int(size) <= MAX_REQUEST:
                return self._json(413, {"error": "invalid_request_size"})
            try:
                raw = self.rfile.read(int(size))
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise ValueError("Expected JSON object")
            except (ValueError, UnicodeDecodeError):
                return self._json(400, {"error": "invalid_json"})
            target = upstreams[provider].rstrip("/") + self.path
            parsed = urllib.parse.urlparse(target)
            if parsed.scheme not in {"https", "http"} or not parsed.hostname:
                return self._json(500, {"error": "invalid_upstream"})
            # Local development upstreams may use HTTP; reject insecure remote hosts.
            if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                return self._json(500, {"error": "insecure_remote_upstream"})
            credential = self.headers.get("Authorization") or self.headers.get("x-api-key", "")
            if not credential:
                return self._json(401, {"error": "missing_api_credential"})
            replay = self.headers.get("X-Cooooost-Cache", "off").lower() == "replay"
            safe, reason = eligible(payload)
            enabled = replay and safe
            streaming = bool(payload.get("stream"))
            namespace = self.headers.get("X-Cooooost-Namespace", "default")
            if len(namespace) > 128:
                return self._json(400, {"error": "namespace_too_long"})
            # Distinguish API organizations/accounts without storing credentials.
            key = request_key(provider, target, payload, credential, namespace)
            if enabled:
                cached = cache.get(key)
                if cached is not None:
                    response, usage = cached
                    cache.record(provider, "hit", avoided=usage)
                    return self._json(200, response, {"X-Cooooost-Cache": "HIT"})
            forwarded = {"Content-Type": "application/json", "Accept": "application/json"}
            for header in ("Authorization", "x-api-key", "anthropic-version", "anthropic-beta", "OpenAI-Organization", "OpenAI-Project"):
                value = self.headers.get(header)
                if value:
                    forwarded[header] = value
            req = urllib.request.Request(target, data=raw, headers=forwarded, method="POST")
            try:
                result = urllib.request.urlopen(req, timeout=timeout)
            except urllib.error.HTTPError as exc:
                result = exc
            except (urllib.error.URLError, TimeoutError, OSError):
                cache.record(provider, "upstream_failure")
                return self._json(502, {"error": "upstream_connection_failed"})
            with result:
                status = result.status if hasattr(result, "status") else result.code
                content_type = result.headers.get("Content-Type", "application/json")
                if streaming and 200 <= status < 300:
                    self.send_response(status)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "close")
                    self.send_header("X-Cooooost-Cache", "BYPASS")
                    self.end_headers()
                    try:
                        while True:
                            chunk = result.read(16384)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
                        pass
                    self.close_connection = True
                    cache.record(provider, "stream_passthrough")
                    return
                incoming = result.read(MAX_RESPONSE + 1)
            if len(incoming) > MAX_RESPONSE:
                return self._json(502, {"error": "upstream_response_too_large"})
            obj = None
            try:
                obj = json.loads(incoming)
            except (ValueError, UnicodeDecodeError):
                pass
            if 200 <= status < 300 and isinstance(obj, dict):
                usage = extract_usage(provider, obj)
                cache.record(provider, "miss" if enabled else "passthrough", usage)
                if enabled and ("choices" in obj or "output" in obj or "content" in obj) and "usage" in obj:
                    cache.put(key, obj, usage)
            else:
                cache.record(provider, "upstream_error")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(incoming)))
            self.send_header("X-Cooooost-Cache", "MISS" if enabled else "BYPASS")
            self.end_headers()
            self.wfile.write(incoming)
    return Handler


def serve(project: str | Path, port: int = 8765, openai: str = "https://api.openai.com",
          anthropic: str = "https://api.anthropic.com", ttl: int = 3600):
    cache = Cache(root_of(project) / "cache.sqlite3", ttl=ttl)
    handler = make_handler(cache, {"openai": openai, "anthropic": anthropic})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print("Cooooost local gateway: http://127.0.0.1:" + str(server.server_port), flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()