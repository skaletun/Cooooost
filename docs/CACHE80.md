# Cache 80: accuracy contract

Cache 80 groups **three independent optimizations**:

1. **Native prompt-prefix reuse**: maximize naturally repeated initial message and tool-definition prefixes. The provider decides cache effectiveness; cached input tokens may receive reduced API pricing but still count toward usage limits.
2. **Exact response replay**: only with `X-Cooooost-Cache: replay`, `temperature: 0`, exact eligible JSON, same credential, namespace, provider and endpoint. Ignores none of the original request fields. TTL default one hour. This avoids a fresh model call and so may save both input and output API tokens, at the cost of using an old reply. It is never appropriate for changing information or actions.
3. **Lossless local archives + scoped retrieval**: original source remains recoverable; selecting relevant chunks may reduce prompt size, but incomplete relevance selection must always be disclosed and verified on demand.

## Cost measurements

- `observed_input_tokens`: upstream-reported input usage for successful non-streamed JSON replies.
- `observed_output_tokens`: upstream-reported output usage.
- `provider_cached_input_tokens`: upstream-reported cached input subset; not all cached tokens are free or exempt from rate limits.
- `avoided_input_tokens_estimate` and `avoided_output_tokens_estimate`: previous successful request usage counted for an exact-replay cache hit. **Counterfactual**, not direct billing evidence.
- `requests.hit`: count of opt-in replay hits. A hit rate of 80% does not imply 80% bill savings or extended 5-hour subscription limits.

## Provider details

[OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching) is enabled by default on supported models and reports usage details such as `cached_tokens`. Caching eligibility and discounts vary by model and endpoint. [Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) supports configurable cache control, subject to model limits. Cooooost relays provider cache controls without rewriting them. Its local replay cannot control provider KV-cache lifecycle.

## Default denials

No replay for streaming responses, tools/function calling, external data toggles, missing explicit `temperature: 0`, absent model, malformed input, or disabled opt-in. No replay is performed by the skill installation itself; the client must explicitly point API requests to the local gateway.

## Correctness and privacy notes

Use replay for stable, read-only workloads where a previously generated response is acceptable. Avoid authentication, financial/medical decisions, searches, tool calls, personal secrets, and rapidly changing data. A changed prompt always hashes to a new key. Cache corruption/expiry produces a miss. Disable with header removal or call `purge-cache` to remove stored replies. The API gateway binds to localhost only. Its SQLite cache is stored locally, not committed.