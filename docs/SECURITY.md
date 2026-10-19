# Local security and data retention

- `.cooooost/` contains potentially sensitive transcripts, checkpoints, indices, and cached model outputs. Keep directory private; do not commit to Git. Root and snapshot files use best-effort POSIX user-only permissions. SQLite file is 0600 on POSIX.
- Only the user opts into saving/replaying completed model responses. Authorization values are never logged or persisted in plaintext; they influence SHA-256 cache isolation. Hashes are not replacements for credential vaults.
- The localhost proxy is not meant for shared or public networks; do not expose it through port-forwarding or tunnels. There is no user login mechanism on `/metrics`.
- Upstreams must be HTTPS except for localhost test upstreams. All upstream hosts and paths are configured explicitly.
- Cache TTL is mandatory and response integrity is checked before reuse. Cache lifetime is **not** source freshness validation. The user must not enable replay where data may change.
- The archive is lossless and only restores to an explicitly selected location; it refuses overwrites by default. The original transcript is not erased.
- Native Claude hook installs are opt-in and preserve existing hooks, with a one-time settings backup. No hook blocks native compaction or modifies Claude's transcript.
- Commands are intended to run locally with the permissions of the current OS user. This package is not a secure multi-tenant sandbox.