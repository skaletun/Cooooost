"""Non-destructive, opt-in agent skill installation and Claude Code lifecycle hooks."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
from .core import archive, checkpoint, init, read_state, root_of, summary, utc, atomic, canon

AGENTS = {
    "claude": Path(".claude/skills/cooooost"),
    "codex": Path(".agents/skills/cooooost"),
    "gemini": Path(".gemini/skills/cooooost"),
    "cursor": Path(".cursor/skills/cooooost"),
    "opencode": Path(".config/opencode/skills/cooooost"),
}


def install_skill(agent: str, home: str | Path | None = None) -> Path:
    if agent not in AGENTS:
        raise ValueError("Supported agents: " + ", ".join(AGENTS))
    dest = (Path(home).expanduser() if home else Path.home()) / AGENTS[agent]
    dest.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).with_name("SKILL.md")
    atomic(dest / "SKILL.md", source.read_bytes())
    return dest


def claude_hook_config(python: str | None = None) -> dict:
    # sys.executable may have spaces; shlex.quote would not be PowerShell safe.
    # Use an executable resolved as simple 'python' entrypoint for cross-platform settings.
    executable = python or "python"
    if not executable.replace("_", "").replace("-", "").isalnum():
        raise ValueError("Use a simple Python command such as python or python3")
    def command(event):
        return {"hooks": [{"type": "command", "command": executable + " -m cooooost hook " + event, "timeout": 20}]}
    return {"SessionStart": [command("SessionStart")],
            "PreCompact": [command("PreCompact")],
            "PostCompact": [command("PostCompact")],
            "SessionEnd": [command("SessionEnd")]}


def install_claude_hooks(home: str | Path | None = None, python: str = "python") -> Path:
    path = (Path(home) if home else Path.home()) / ".claude" / "settings.json"
    if path.exists():
        config = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or not isinstance(config.get("hooks", {}), dict):
            raise ValueError("Unsupported Claude settings; refusing to overwrite")
    else:
        config = {}
    hooks = config.setdefault("hooks", {})
    desired = claude_hook_config(python)
    for event, group in desired.items():
        existing = hooks.setdefault(event, [])
        if not isinstance(existing, list):
            raise ValueError("Invalid existing hooks configuration")
        for hook in group:
            if hook not in existing:
                existing.append(hook)
    if path.exists():
        backup = path.with_name("settings.cooooost-backup.json")
        if not backup.exists():
            atomic(backup, path.read_bytes())
    atomic(path, canon(config) + b"\n")
    return path


def process_hook(event: str, raw: str) -> dict | None:
    """Always fail-open; hook does not edit Claude transcript or block compaction."""
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        cwd = data.get("cwd")
        if not cwd or not Path(cwd).is_dir():
            return None
        init(cwd)
        if data.get("transcript_path") and Path(data["transcript_path"]).is_file():
            from .watch import register
            register(cwd, data["transcript_path"])
        if event == "SessionStart":
            return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": summary(cwd)}}
        transcript = data.get("transcript_path")
        if event in {"PreCompact", "SessionEnd"}:
            if transcript and Path(transcript).is_file():
                archive(cwd, transcript)
                from .watch import register
                register(cwd, transcript)
            checkpoint(cwd)
        if event == "PostCompact":
            # Provider-generated summary is stored in the ledger as evidence, not as replacement.
            from .core import update
            compact_summary = data.get("compact_summary")
            if isinstance(compact_summary, str) and compact_summary:
                output = root_of(cwd) / "native-compactions" / (utc().replace(":", "-") + ".txt")
                atomic(output, compact_summary.encode("utf-8"))
                update(cwd, append={"sources": "Native compaction summary: " + str(output)})
        return None
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None