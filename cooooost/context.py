"""Lossless, provenance-linked project context retrieval. Summaries are not facts."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from .core import archive, root_of

TOKENS = re.compile(r"[\w\-]{2,}", re.UNICODE)


def words(text: str) -> set[str]:
    return set(w.casefold() for w in TOKENS.findall(text))


def ingest(project: str | Path, source: str | Path, chunk_chars: int = 3200) -> dict:
    if chunk_chars < 128:
        raise ValueError("Chunk size must be >=128")
    file = Path(source).expanduser().resolve(strict=True)
    raw = file.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Only UTF-8 files supported for indexing; archive binary separately") from exc
    metadata = archive(project, file)
    records = []
    # Deterministic paragraph chunking. Each chunk retains the exact offset in source.
    for i in range(0, len(text), chunk_chars):
        piece = text[i:i + chunk_chars]
        records.append({"offset": i, "length": len(piece), "sha256": hashlib.sha256(piece.encode()).hexdigest(),
                        "terms": sorted(words(piece))})
    index_path = root_of(project) / "indices" / (metadata["sha256"] + ".json")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    from .core import atomic, canon
    atomic(index_path, canon({"source_sha256": metadata["sha256"], "origin": str(file),
                              "chunks": records, "chunk_chars": chunk_chars}))
    return {"sha256": metadata["sha256"], "chunks": len(records), "index": str(index_path)}


def retrieve(project: str | Path, query: str, max_chars: int = 12000) -> dict:
    """Strict budget: references never replace required full original evidence."""
    if max_chars < 256:
        raise ValueError("Budget too small")
    terms = words(query)
    found = []
    root = root_of(project)
    from .core import restore
    import tempfile
    for index in sorted((root / "indices").glob("*.json")):
        data = json.loads(index.read_bytes())
        sha = data["source_sha256"]
        # Read archive without modifying project and verify digest on every access.
        import gzip
        raw = gzip.decompress((root / "archive" / sha[:2] / (sha + ".gz")).read_bytes())
        if hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError("Archive corruption: " + sha)
        text = raw.decode("utf-8")
        for chunk in data["chunks"]:
            piece = text[chunk["offset"]:chunk["offset"] + chunk["length"]]
            if hashlib.sha256(piece.encode()).hexdigest() != chunk["sha256"]:
                raise ValueError("Chunk corruption: " + sha)
            overlap = len(terms & set(chunk["terms"]))
            if overlap:
                found.append((overlap, data["origin"], sha, chunk["offset"], piece))
    found.sort(key=lambda r: (-r[0], r[1], r[3]))
    selected, spent = [], 0
    for score, origin, sha, offset, piece in found:
        if spent + len(piece) > max_chars:
            continue
        selected.append({"score": score, "source": origin, "source_sha256": sha,
                         "offset": offset, "text": piece})
        spent += len(piece)
    return {"query": query, "chunks": selected, "returned_chars": spent,
            "available_chunks": len(found), "complete": len(selected) == len(found),
            "notice": "Read original sources before decisions requiring omitted evidence."}