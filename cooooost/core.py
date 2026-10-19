"""Canonical serialization, safe filesystem IO, project state and immutable evidence."""
from __future__ import annotations

from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
from typing import Any

SCHEMA = 2
FIELDS = ("acceptance_criteria", "constraints", "decisions", "files_changed", "tests", "blockers", "next_steps", "sources")


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def root_of(project: str | Path) -> Path:
    return Path(project).expanduser().resolve() / ".cooooost"


def atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        try:
            os.fchmod(fd, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def initial() -> dict:
    return {"schema": SCHEMA, "goal": "", "updated_at": utc(), **{f: [] for f in FIELDS}}


def read_state(project: str | Path) -> dict:
    path = root_of(project) / "state.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return initial()
    if data.get("schema") == 1 and all(isinstance(data.get(f), list) for f in FIELDS):
        original = path.read_bytes()
        backup = path.with_name("state.schema1." + digest(original)[:12] + ".json")
        if not backup.exists():
            atomic(backup, original)
        # Preserve additional legacy metadata rather than discarding it.
        extras = {k: v for k, v in data.items() if k not in initial()}
        data = {**initial(), **data, "schema": SCHEMA, "legacy_extra": extras}
        atomic(path, canon(data) + b"\n")
    if data.get("schema") != SCHEMA or any(not isinstance(data.get(f), list) for f in FIELDS):
        raise ValueError("Invalid state schema; use doctor and recover, do not overwrite")
    return data


def init(project: str | Path) -> Path:
    root = root_of(project)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    path = root / "state.json"
    if not path.exists():
        atomic(path, canon(initial()) + b"\n")
    return path


def update(project: str | Path, goal: str | None = None, append: dict[str, str] | None = None) -> dict:
    init(project)
    state = read_state(project)
    if goal is not None:
        state["goal"] = goal
    for field, value in (append or {}).items():
        if field not in FIELDS:
            raise ValueError("Unsupported ledger field: " + field)
        if value and value not in state[field]:
            state[field].append(value)
    state["updated_at"] = utc()
    atomic(root_of(project) / "state.json", canon(state) + b"\n")
    return state


def checkpoint(project: str | Path) -> Path:
    init(project)
    state = read_state(project)
    payload = canon(state)
    record = {"created": utc(), "sha256": digest(payload), "state": state}
    path = root_of(project) / "checkpoints" / (secrets.token_hex(10) + ".json")
    atomic(path, canon(record))
    return path


def verified_checkpoints(project: str | Path) -> list[Path]:
    paths = sorted((root_of(project) / "checkpoints").glob("*.json"), key=lambda p: p.stat().st_mtime)
    for path in paths:
        record = json.loads(path.read_bytes())
        if digest(canon(record["state"])) != record["sha256"]:
            raise ValueError("Checkpoint integrity mismatch: " + str(path))
    return paths


def recover(project: str | Path) -> dict:
    files = verified_checkpoints(project)
    if not files:
        raise FileNotFoundError("No verified checkpoints")
    state = json.loads(files[-1].read_bytes())["state"]
    atomic(root_of(project) / "state.json", canon(state) + b"\n")
    return state


def archive(project: str | Path, source: str | Path) -> dict:
    """Content-addressed lossless gzip archive. Never deletes or alters source."""
    path = Path(source).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError("Source must be a regular file")
    raw = path.read_bytes()
    sha = digest(raw)
    destination = root_of(project) / "archive" / sha[:2] / (sha + ".gz")
    if not destination.exists():
        atomic(destination, gzip.compress(raw, compresslevel=9, mtime=0))
    return {"sha256": sha, "bytes": len(raw), "source": str(path), "stored": str(destination)}


def restore(project: str | Path, sha: str, output: str | Path, overwrite: bool = False) -> Path:
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("Invalid SHA-256")
    path = root_of(project) / "archive" / sha[:2] / (sha + ".gz")
    raw = gzip.decompress(path.read_bytes())
    if digest(raw) != sha:
        raise ValueError("Archive integrity check failed")
    target = Path(output).expanduser().resolve()
    if target.exists() and not overwrite:
        raise FileExistsError(str(target))
    atomic(target, raw)
    return target


def summary(project: str | Path, max_chars: int = 6000) -> str:
    state = read_state(project)
    fragments = ["Cooooost verified ledger (recheck against newest user request):", "Goal: " + state["goal"]]
    for field in FIELDS:
        if state[field]:
            fragments.append(field.replace("_", " ").title() + ":")
            for entry in state[field]:
                fragments.append("- " + entry)
    output = "\n".join(fragments)
    if len(output) > max_chars:
        # Avoid silently dropping criteria: point to unabridged ledger.
        return "Cooooost state exceeds safe injection budget. Read full ledger: " + str(root_of(project) / "state.json")
    return output