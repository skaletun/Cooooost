"""Primary command-line API (stdlib-only runtime)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from . import __version__
from . import core


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cooooost", description="Local-first quality-preserving agent context and cache")
    p.add_argument("--version", action="version", version=__version__)
    s = p.add_subparsers(dest="action", required=True)
    s.add_parser("init").add_argument("--project", default=".")
    u = s.add_parser("update")
    u.add_argument("--project", default=".")
    u.add_argument("--goal")
    for field in core.FIELDS:
        u.add_argument("--" + field.replace("_", "-"), dest=field)
    for name in ("checkpoint", "verify", "recover", "status", "summary", "doctor", "cycle", "stats", "purge-cache"):
        s.add_parser(name).add_argument("--project", default=".")
    a = s.add_parser("archive"); a.add_argument("source"); a.add_argument("--project", default=".")
    a = s.add_parser("restore"); a.add_argument("sha256"); a.add_argument("output"); a.add_argument("--project", default="."); a.add_argument("--overwrite", action="store_true")
    a = s.add_parser("ingest"); a.add_argument("source"); a.add_argument("--project", default="."); a.add_argument("--chunk-chars", type=int, default=3200)
    a = s.add_parser("retrieve"); a.add_argument("query"); a.add_argument("--project", default="."); a.add_argument("--max-chars", type=int, default=12000)
    a = s.add_parser("daemon"); a.add_argument("--project", default="."); a.add_argument("--interval-min", type=float, default=7); a.add_argument("--interval-max", type=float, default=13)
    a = s.add_parser("serve"); a.add_argument("--project", default="."); a.add_argument("--port", type=int, default=8765); a.add_argument("--ttl", type=int, default=3600)
    a.add_argument("--openai-upstream", default="https://api.openai.com"); a.add_argument("--anthropic-upstream", default="https://api.anthropic.com")
    a = s.add_parser("install"); a.add_argument("--agent", required=True, choices=["claude", "codex", "gemini", "cursor", "opencode", "all"]); a.add_argument("--home"); a.add_argument("--claude-hooks", action="store_true"); a.add_argument("--python-command", default="python")
    a = s.add_parser("hook"); a.add_argument("event", choices=["SessionStart", "PreCompact", "PostCompact", "SessionEnd"])
    return p


def run(argv=None) -> int:
    args = parser().parse_args(argv)
    project = getattr(args, "project", ".")
    try:
        from .cache import Cache
        from .context import ingest, retrieve
        from .integrations import install_skill, install_claude_hooks, process_hook
        from .watch import cycle, daemon
        act = args.action
        if act == "init":
            result = str(core.init(project))
        elif act == "update":
            fields = {field: getattr(args, field) for field in core.FIELDS if getattr(args, field)}
            result = core.update(project, args.goal, fields)
        elif act == "checkpoint":
            result = str(core.checkpoint(project))
        elif act == "verify":
            result = {"verified_checkpoints": len(core.verified_checkpoints(project))}
        elif act == "recover":
            result = core.recover(project)
        elif act == "status":
            result = core.read_state(project)
        elif act == "summary":
            result = core.summary(project)
        elif act == "archive":
            result = core.archive(project, args.source)
        elif act == "restore":
            result = str(core.restore(project, args.sha256, args.output, args.overwrite))
        elif act == "ingest":
            result = ingest(project, args.source, args.chunk_chars)
        elif act == "retrieve":
            result = retrieve(project, args.query, args.max_chars)
        elif act == "cycle":
            result = cycle(project)
        elif act == "daemon":
            daemon(project, args.interval_min, args.interval_max)
            return 0
        elif act == "stats":
            result = Cache(core.root_of(project) / "cache.sqlite3").stats()
        elif act == "purge-cache":
            result = {"purged_entries": Cache(core.root_of(project) / "cache.sqlite3").purge()}
        elif act == "doctor":
            state = core.read_state(project)
            result = {"state_valid": True, "checkpoint_count": len(core.verified_checkpoints(project)),
                      "version": __version__, "has_goal": bool(state["goal"]),
                      "quality_gate": "Do not claim completion without task-specific verification"}
        elif act == "serve":
            from .proxy import serve
            serve(project, args.port, args.openai_upstream, args.anthropic_upstream, args.ttl)
            return 0
        elif act == "install":
            agents = list(("claude", "codex", "gemini", "cursor", "opencode")) if args.agent == "all" else [args.agent]
            result = {agent: str(install_skill(agent, args.home)) for agent in agents}
            if args.claude_hooks:
                result["claude_hooks"] = str(install_claude_hooks(args.home, args.python_command))
        elif act == "hook":
            result = process_hook(args.event, sys.stdin.read())
            if result is not None:
                print(json.dumps(result, ensure_ascii=False))
            return 0
        else:
            raise ValueError("Unsupported command")
        if isinstance(result, (dict, list)):
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(result)
        return 0
    except (FileNotFoundError, FileExistsError, ValueError, PermissionError, OSError) as exc:
        print("Cooooost error: " + str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def main():
    raise SystemExit(run())