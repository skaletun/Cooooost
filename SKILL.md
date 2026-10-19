---
name: cooooost
description: Local-first context checkpointing and quality-preserving workflow guidance for AI agents.
---
# Cooooost

Maintain an explicit task ledger: goal, acceptance criteria, constraints, decisions, changed files, test results, blockers, next steps and source references. Preserve original source material. Reuse verified tool results when inputs are unchanged. Prefer targeted reads and diffs over full reloads. Never skip verification or reduce task scope to save tokens.

Use `python scripts/cooooost.py init --project .` to initialize, `update` to record progress, and `checkpoint` to save a validated snapshot. Optional `daemon --interval-min 7 --interval-max 13` creates snapshots at random intervals. Snapshots do not force model-side context compression or change provider limits. On resumption, read `.cooooost/state.json` and check against original evidence before continuing.
