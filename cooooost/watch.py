"""7–13-minute checkpoint scheduler; archives known transcripts losslessly.

This does not issue /compact or control hidden model context.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import random
import time
from .core import archive, atomic, canon, checkpoint, root_of


def register(project: str | Path, transcript: str | Path) -> None:
    path = Path(transcript).resolve()
    if not path.is_file():
        return
    dest = root_of(project) / "sessions" / (path.name + ".json")
    atomic(dest, canon({"transcript": str(path)}))


def cycle(project: str | Path) -> dict:
    root = root_of(project)
    results = {"archived": 0, "missing": 0, "checkpoint": ""}
    for record in (root / "sessions").glob("*.json"):
        try:
            source = Path(json.loads(record.read_text(encoding="utf-8"))["transcript"])
            if source.is_file():
                archive(project, source)
                results["archived"] += 1
            else:
                results["missing"] += 1
        except (ValueError, KeyError, OSError):
            results["missing"] += 1
    results["checkpoint"] = str(checkpoint(project))
    return results


def daemon(project: str | Path, minimum: float = 7, maximum: float = 13,
           iterations: int | None = None, sleep=time.sleep) -> list[dict]:
    if not 0 < minimum <= maximum:
        raise ValueError("Require 0 < minimum <= maximum")
    reports = []
    completed = 0
    while iterations is None or completed < iterations:
        sleep(random.uniform(minimum, maximum) * 60)
        result = cycle(project)
        reports.append(result)
        print(json.dumps(result), flush=True)
        completed += 1
    return reports