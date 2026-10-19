# Cache 80 — design and integration contract

Cache 80 is a target optimization profile, not a guaranteed 80% reduction.

## What is implemented
- Exact-match request caching with SHA-256 keys incorporating provider, model, system prompt, messages, tools, parameters, and namespace.
- TTL and integrity validation.
- Atomic cache writes.
- Lossless context chunk manifest and reconstruction verification.

## Critical correctness rules
- Never reuse a response for a changed input, tool schema, model or generation parameter.
- Do not cache nondeterministic or externally changing operations (live search, purchases, destructive operations, personal data) unless the caller explicitly chooses a valid freshness policy.
- Never send a summary in place of necessary source data without retrieval access and verification.
- Never claim that a context manifest itself reduces model tokens: savings occur only if the agent sends shorter verified relevant content or provider-supported cached prefixes.
- Exact-cache hits avoid model calls; misses incur normal costs.
- Provider-side prompt caching is separate and requires provider integration and usage telemetry.
- The same prompt with temperature > 0 may produce different valid answers; exact response reuse must be an explicit caller choice.

## Python integration

```python
from scripts.cache80 import ExactCache, key_for

cache = ExactCache(".cooooost/cache", ttl=3600)
messages = [{"role": "user", "content": "Explain this stable input"}]
key = key_for("provider", "model-id", "system prompt", messages,
              parameters={"temperature": 0}, namespace="project")
answer = cache.get(key)
if answer is None:
    answer = call_your_provider(messages)
    cache.put(key, answer)
```

The `call_your_provider` symbol represents an application-provided API adapter; this repository does not bundle an API client.

## Future milestones
1. Provider-specific prompt-cache adapters and usage measurements.
2. Claude Code hook integration with tested lifecycle handling.
3. Dependency graph for incremental repository context retrieval.
4. Privacy-aware eviction, cache metrics and adaptive policies.
5. Benchmarks with task-level correctness regression gates.
