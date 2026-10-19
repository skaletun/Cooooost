# Cooooost architecture

## Trust boundary

- **Original source data**: canonical; no deletion or summary-as-replacement.
- **Ledger**: a structured model-maintained map of objective, constraints, acceptance criteria, decisions, evidence, test results, blockers and next steps.
- **Snapshot**: immutable SHA-256-verified copy of ledger, created manually, before native compaction, or periodically in daemon.
- **Transcript archive**: deterministic gzip with SHA-256 of **uncompressed** bytes, stored content-addressed under `.cooooost/archive`.
- **Index**: deterministic UTF-8 chunk offsets + SHA-256 hash per chunk, derived from full archive. Retrieval verifies archive and chunks, and reports omissions.
- **Provider prompt cache**: managed by provider. Preserving stable prefix and tool schemas can improve hit rate without changing response semantics.
- **Replay cache**: separate optional mode. A miss makes the original API call; a hit returns a stored prior result. It is **not** transparent equivalence to fresh model generation. Disable for volatile or side-effecting tasks.

## Lifecycle

1. Install skill (manual, multi-agent) and optional Claude Code hooks.
2. On SessionStart, register transcript and inject small ledger summary.
3. On PreCompact, archive original JSONL and snapshot ledger before native compaction.
4. On PostCompact, save native compact summary as a linked artifact (do not replace originals).
5. Daemon may independently archive registered transcript paths and snapshot ledger at 7–13-minute intervals while running.
6. On restore, verify checksums, consult originals when needed, then continue normal quality gates.

No model is called by archive, index, daemon, CLI or hook. The ledger requires accurate entries supplied by the agent or user. There is no reliable way for a local watcher to infer the **semantic** state of a private hidden reasoning context.

## Cache flow

`client → local loopback HTTP gateway → eligible? → opt-in? → exact hit? → upstream provider → usage metrics → optional local cache → client`

Everything else is passed through unchanged. Streaming is delivered without response replay. The SQLite data never stores plaintext credentials; the cache key includes the credential hash for isolation. Text of cached *responses* is stored locally and may contain sensitive content; enable replay only for suitable requests.

## Why 80% cannot be guaranteed

Native cache savings depend on provider model, prompt length, prefix identity, cache expiration, traffic and separate input/output pricing. A replay hit can avoid a model call but is only correct when a previous response is acceptable; new generation may differ even at temperature 0. The scheduler only persists known context; it cannot force provider truncation or reset rate windows. Cost reductions should be benchmarked on task-level quality and real billing.