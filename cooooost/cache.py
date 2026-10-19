"""Exact-response opt-in cache and genuine provider-token accounting.

Never sends changed prompts in place of originals. Defaults to no replay.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
import time
from pathlib import Path
from typing import Any
from .core import canon, digest


def request_key(provider: str, endpoint: str, payload: dict, identity: str, namespace: str) -> str:
    return digest(canon({"provider": provider, "endpoint": endpoint,
                         "payload": payload, "identity": digest(identity.encode()), "namespace": namespace}))


def eligible(payload: dict) -> tuple[bool, str]:
    """Deny by default when side effects, unknown semantics or streaming are present."""
    if not isinstance(payload, dict):
        return False, "invalid_request"
    if payload.get("stream"):
        return False, "streaming_not_supported"
    if payload.get("tools") or payload.get("functions") or payload.get("tool_choice"):
        return False, "tool_calls_not_safe_to_replay"
    if payload.get("web_search_options") or payload.get("attachments"):
        return False, "external_or_dynamic_data"
    if not payload.get("model"):
        return False, "missing_model"
    # Replay is identical to previously successful text response, but not equivalent to
    # fresh generation for stochastic requests; require deterministic intent.
    if payload.get("temperature") != 0:
        return False, "requires_explicit_temperature_zero"
    return True, "eligible"


def extract_usage(provider: str, response: dict) -> dict[str, int]:
    data = response.get("usage") or {}
    if provider == "anthropic":
        return {"input": int(data.get("input_tokens", 0)),
                "output": int(data.get("output_tokens", 0)),
                "provider_cache_read": int(data.get("cache_read_input_tokens", 0)),
                "provider_cache_write": int(data.get("cache_creation_input_tokens", 0))}
    details = data.get("prompt_tokens_details") or data.get("input_tokens_details") or {}
    return {"input": int(data.get("prompt_tokens", data.get("input_tokens", 0))),
            "output": int(data.get("completion_tokens", data.get("output_tokens", 0))),
            "provider_cache_read": int(details.get("cached_tokens", 0)),
            "provider_cache_write": int(details.get("cache_write_tokens", 0))}


class Cache:
    def __init__(self, filename: str | Path, ttl: int = 3600):
        if ttl < 1:
            raise ValueError("TTL must be positive")
        self.filename = Path(filename)
        self.filename.parent.mkdir(parents=True, exist_ok=True)
        if not self.filename.exists():
            fd = os.open(self.filename, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            os.close(fd)
        try:
            os.chmod(self.filename, 0o600)
        except OSError:
            pass
        self.ttl = ttl
        self._lock = threading.RLock()
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS responses (
                key TEXT PRIMARY KEY, data TEXT NOT NULL, checksum TEXT NOT NULL,
                created REAL NOT NULL, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS requests (
                time REAL NOT NULL, provider TEXT NOT NULL, status TEXT NOT NULL,
                input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
                provider_cached_tokens INTEGER NOT NULL, avoided_input_tokens INTEGER NOT NULL,
                avoided_output_tokens INTEGER NOT NULL
            )""")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.filename), timeout=20)
        try:
            db.execute("PRAGMA busy_timeout=20000")
            with db:
                yield db
        finally:
            db.close()

    def get(self, key: str) -> tuple[dict, dict] | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT data, checksum, created, input_tokens, output_tokens FROM responses WHERE key=?", (key,)).fetchone()
            if not row:
                return None
            raw, checksum, created, inputs, outputs = row
            if time.time() - created > self.ttl or digest(raw.encode()) != checksum:
                db.execute("DELETE FROM responses WHERE key=?", (key,))
                return None
            return json.loads(raw), {"input": inputs, "output": outputs}

    def put(self, key: str, response: dict, usage: dict) -> None:
        data = canon(response).decode("utf-8")
        with self._lock, self._connect() as db:
            db.execute("INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?, ?, ?)",
                       (key, data, digest(data.encode()), time.time(), usage["input"], usage["output"]))

    def record(self, provider: str, status: str, usage: dict | None = None,
               avoided: dict | None = None) -> None:
        usage = usage or {}
        avoided = avoided or {}
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO requests VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (time.time(), provider, status, usage.get("input", 0),
                        usage.get("output", 0), usage.get("provider_cache_read", 0),
                        avoided.get("input", 0), avoided.get("output", 0)))

    def stats(self) -> dict:
        with self._lock, self._connect() as db:
            counts = db.execute("SELECT status, COUNT(*) FROM requests GROUP BY status").fetchall()
            totals = db.execute("""SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0),
                                COALESCE(SUM(provider_cached_tokens),0), COALESCE(SUM(avoided_input_tokens),0),
                                COALESCE(SUM(avoided_output_tokens),0) FROM requests""").fetchone()
            entries = db.execute("SELECT COUNT(*) FROM responses").fetchone()[0]
        return {"requests": dict(counts), "entries": entries,
                "observed_input_tokens": totals[0], "observed_output_tokens": totals[1],
                "provider_cached_input_tokens": totals[2],
                "avoided_input_tokens_estimate": totals[3],
                "avoided_output_tokens_estimate": totals[4],
                "warning": "Avoided tokens are a counterfactual based on previous responses, not measured provider billing."}

    def purge(self) -> int:
        with self._lock, self._connect() as db:
            count = db.execute("SELECT COUNT(*) FROM responses").fetchone()[0]
            db.execute("DELETE FROM responses")
        return count