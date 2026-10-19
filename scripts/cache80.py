"""Cache 80: exact content-addressed reuse, not lossy answer substitution."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

def key_for(provider, model, system, messages, tools=None, parameters=None, namespace="default"):
    request = {"provider": provider, "model": model, "system": system,
               "messages": messages, "tools": tools or [], "parameters": parameters or {},
               "namespace": namespace}
    return hashlib.sha256(canonical(request)).hexdigest()

class ExactCache:
    def __init__(self, root, ttl=86400):
        self.root = Path(root).resolve()
        self.ttl = ttl

    def _path(self, key):
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("Invalid cache key")
        return self.root / key[:2] / (key + ".json")

    def get(self, key):
        path = self._path(key)
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            if entry["key"] != key or time.time() - entry["created"] > self.ttl:
                return None
            if hashlib.sha256(canonical(entry["value"])).hexdigest() != entry["digest"]:
                return None
            return entry["value"]
        except (FileNotFoundError, ValueError, KeyError, TypeError, OSError):
            return None

    def put(self, key, value):
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"key": key, "created": time.time(), "value": value,
                 "digest": hashlib.sha256(canonical(value)).hexdigest()}
        fd, tmp = tempfile.mkstemp(prefix=".cache-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(canonical(entry))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

def context_manifest(chunks):
    """Store all chunks losslessly; return short reference manifest."""
    index = []
    for i, text in enumerate(chunks):
        raw = text.encode("utf-8")
        index.append({"index": i, "sha256": hashlib.sha256(raw).hexdigest(),
                      "bytes": len(raw)})
    return index

def restore(chunks, manifest):
    if len(chunks) != len(manifest):
        raise ValueError("Missing context chunks")
    for i, (text, item) in enumerate(zip(chunks, manifest)):
        if item["index"] != i or hashlib.sha256(text.encode("utf-8")).hexdigest() != item["sha256"]:
            raise ValueError("Context integrity check failed")
    return "".join(chunks)
