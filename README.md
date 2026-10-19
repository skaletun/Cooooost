# Cooooost

**Local-first AI agent context preservation and usage optimization — without trimming task requirements.**

Cooooost is a portable [Agent Skill](SKILL.md), zero-third-party-runtime-dependency Python CLI, integrity-checked context archive, selective retrieval index and **opt-in Cache 80** gateway for OpenAI and Anthropic HTTP APIs.

> **Cache 80 means a target, not a guaranteed 80% saving.** No skill can expand ChatGPT/Claude subscription limits or force a private model to compress its context. Response replay is not the same as fresh generation; it is disabled unless requested. Provider-native prefix caching does not remove input tokens from rate limits. Cooooost records both native cached input and estimated avoided replay tokens separately.

## Install (Windows, macOS, Linux)

Requirements: Python 3.10+; no runtime PyPI dependencies.

```bash
git clone https://github.com/skaletun/Cooooost.git
cd Cooooost
python -m pip install .
python -m cooooost --version
python -m cooooost install --agent all
```

The installer places `SKILL.md` in the standard user skill directories for **Claude Code, Codex, Gemini CLI, Cursor, OpenCode**. Each agent must support skills in the specified directory. Restart the agent to load new skills. `--home` permits installation into a custom base directory. The installer only writes its own skill file; it never touches existing prompts.

For **Claude Code lifecycle hooks**, opt in explicitly (existing settings are backed up and preserved):

```bash
python -m cooooost install --agent claude --claude-hooks
```

On systems with only `python3`, use `python3 -m cooooost install --agent claude --claude-hooks --python-command python3`. Hooks execute when Claude Code fires events; an agent that does not support these hooks still supports the skill's manual workflow. Hook installation does not start a background daemon.

## Track tasks and restore context

```bash
python -m cooooost init --project .
python -m cooooost update --project . --goal "Ship the feature completely" --acceptance-criteria "All integration tests pass" --constraints "Do not remove functionality"
python -m cooooost update --project . --files-changed "src/main.ts" --tests "pytest: 34 passed" --next-steps "Visual check"
python -m cooooost checkpoint --project .
python -m cooooost status --project .
python -m cooooost verify --project .
python -m cooooost recover --project .
```

A snapshot is an exact copy of the ledger. Claude Code hooks also archive its transcript file before native compaction. Both original transcript and compressed archive remain available; a recovery summary never replaces originals. `recover` overwrites the *ledger state only* with the latest verified checkpoint, not project files.

### 7–13 minute automatic snapshots

```bash
python -m cooooost daemon --project . --interval-min 7 --interval-max 13
```

Keep the command running in a dedicated terminal/process. The daemon creates snapshots and gzip archives of transcripts previously registered by Claude Code hooks. It has no permission to call Claude's `/compact` or change ChatGPT's hidden model context. It does not start automatically when you install the skill.

## Cache 80: real API passthrough, opt-in replay

```bash
python -m cooooost serve --project . --port 8765
```

Configure an OpenAI-compatible application to use `http://127.0.0.1:8765/v1` rather than `https://api.openai.com/v1`, with its **existing API key**. Supported endpoints: `POST /v1/chat/completions`, `POST /v1/responses` and `POST /v1/messages` (Anthropic). Non-streaming requests are forwarded byte-for-byte as submitted; streaming SSE responses are passed through without caching. Only endpoint URL and explicitly required API headers are forwarded; the gateway never logs request content.

Caching is **off** by default. To enable exact replay for a particular non-streaming, tool-free request, set:

```http
X-Cooooost-Cache: replay
X-Cooooost-Namespace: my-project
```

The request must include `temperature: 0` and must not use tool calls or dynamic online data. Cache keys include provider, exact target endpoint, full JSON input, user credential hash and namespace. **Do not enable replay for current facts, live search, side effects, security-critical answers, or privacy-sensitive traffic.** Returned results bear `X-Cooooost-Cache: HIT`, `MISS`, or `BYPASS`. An exact hit reuses the *old* response (including old ID and usage); it does not regenerate a response. Freshness is controlled by local TTL (default 3600 seconds).

For native prompt caching, send normal identical prefixes and keep using your provider. The gateway does **not** rewrite prompts or insert unofficial cache parameters; provider caching is left intact.

Usage metrics:

```bash
python -m cooooost stats --project .
python -m cooooost purge-cache --project .
```

`provider_cached_input_tokens` reflects token data reported by real upstream API calls. `avoided_*_tokens_estimate` means the token counts of previously generated replies replayed without new upstream calls. **They must not be added together as actual billable-token savings.**

## Lossless source archive and retrieval

```bash
python -m cooooost archive ./history.jsonl --project .
python -m cooooost ingest ./specification.md --project .
python -m cooooost retrieve "acceptance criteria" --project . --max-chars 12000
python -m cooooost restore <sha256-from-archive> ./restored-history.jsonl --project .
```

Indexing only works for UTF-8 text. `archive` handles any file (including binary). SHA-256 validation detects accidental changes. A retrieval result includes offsets, checksums, `complete` (whether all matching chunks were included), and links to original files. Original files are never modified or deleted.

## Testing and troubleshooting

```bash
python -m unittest discover -s tests -v
python -m cooooost doctor --project .
```

Tests exercise real local HTTP forwarding, response replay, isolation between API credentials, streaming passthrough, cache corruption/expiry, checkpoint recovery, agent installers, Claude hooks and binary archive restoration — without consuming provider tokens. GitHub Actions tests Python 3.10–3.13 on Windows, Linux and macOS.

See [Architecture](docs/ARCHITECTURE.md), [Cache 80](docs/CACHE80.md), and [Security](docs/SECURITY.md).

MIT License.