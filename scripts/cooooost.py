#!/usr/bin/env python3
"""Dependency-free local task-ledger snapshots."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import random
import time

def paths(project):
    base = Path(project).resolve() / ".cooooost"
    return base / "state.json", base / "checkpoints"

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + str(os.getpid()) + ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)

def load(project):
    state, _ = paths(project)
    with state.open(encoding="utf-8") as stream:
        result = json.load(stream)
    if result.get("schema") != 1:
        raise ValueError("Invalid ledger schema")
    return result

def init(project):
    state, folder = paths(project)
    folder.mkdir(parents=True, exist_ok=True)
    if not state.exists():
        save(state, {"schema": 1, "goal": "", "acceptance_criteria": [], "constraints": [], "decisions": [], "files_changed": [], "tests": [], "blockers": [], "next_steps": [], "sources": []})

def update(project, goal=None, next_step=None):
    state, _ = paths(project)
    data = load(project)
    if goal is not None:
        data["goal"] = goal
    if next_step:
        data["next_steps"].append(next_step)
    save(state, data)

def checkpoint(project):
    data = load(project)
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    digest = hashlib.sha256(payload).hexdigest()
    _, folder = paths(project)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = folder / (stamp + "-" + digest[:12] + ".json")
    save(destination, {"sha256": digest, "state": data})
    return destination

def verify(project):
    _, folder = paths(project)
    count = 0
    for path in folder.glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        payload = json.dumps(record["state"], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        if hashlib.sha256(payload).hexdigest() != record["sha256"]:
            raise ValueError("Corrupted checkpoint: " + str(path))
        count += 1
    return count

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "update", "checkpoint", "status", "verify", "daemon"])
    parser.add_argument("--project", default=".")
    parser.add_argument("--goal")
    parser.add_argument("--next", dest="next_step")
    parser.add_argument("--interval-min", type=float, default=7)
    parser.add_argument("--interval-max", type=float, default=13)
    args = parser.parse_args()
    if args.command == "init":
        init(args.project)
    elif args.command == "update":
        update(args.project, args.goal, args.next_step)
    elif args.command == "checkpoint":
        print(checkpoint(args.project))
    elif args.command == "status":
        print(json.dumps(load(args.project), indent=2, ensure_ascii=False))
    elif args.command == "verify":
        print(verify(args.project))
    else:
        if not 0 < args.interval_min <= args.interval_max:
            parser.error("Require 0 < interval-min <= interval-max")
        init(args.project)
        try:
            while True:
                time.sleep(random.uniform(args.interval_min, args.interval_max) * 60)
                print(checkpoint(args.project), flush=True)
        except KeyboardInterrupt:
            return

if __name__ == "__main__":
    main()
