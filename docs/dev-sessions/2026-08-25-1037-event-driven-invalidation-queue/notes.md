## Phase 1 — durable queue core

- Queue state uses immutable delivery/invalidation rows and coalesces only `dirty_targets`; a new generation clears an older lease and backoff, so a stale acknowledgement cannot erase newly observed work.
- Every store operation runs only local SQLite work in a short transaction. Timestamps are normalized at the storage boundary to UTC RFC 3339 strings.
- Migrations are applied in one `BEGIN EXCLUSIVE` transaction without `executescript`, which would implicitly commit and break migration rollback semantics.
- Configuration is deliberately strict and credential-free. It validates only the shared database, retention, scan, repository, and board fields.
- Phase verification: `make events-test` (15 passed), `make lint`, `make typecheck`, and `make check` (721 passed, 2 skipped) all passed on 2026-08-25.

## Phase 2 — verified webhook ingestion

- The receiver uses a local asyncio lock plus `asyncio.to_thread` for every SQLite enqueue. This preserves serialized writes without blocking the ASGI event loop, and the request stays pending until the store call returns.
- HMAC checks operate on streamed exact bytes before JSON parsing. Malformed supported identities return 400 without persistence; verified unknown/unconfigured inputs remain immutable diagnostic deliveries.
- `serve` accepts `--config` after the subcommand like every queue command. Its secret comes only from an owner-only regular file named by `AGENT_SESSION_WEBHOOK_SECRET_FILE`; one terminal newline is stripped.
- Phase verification: normalizer focused suite 55 passed; webhook/CLI focused suite 9 passed; `make events-test`, `make lint`, `make typecheck`, and `make check` passed on 2026-08-25.

### Review fix round 1

- SQLite contention now maps to QueueBusy at the store boundary with the original sqlite exception chained; non-integrity operational/database failures map to QueueUnavailable, while application exceptions and foreign-key integrity failures still roll back and propagate unchanged.
- Action parsing distinguishes absent from malformed: absent is valid only for status/ping, a present non-string is malformed, and only a present unknown string is ignored_unknown_action.
- The receiver validates the `sha256=` plus 64-hex digest syntax before comparison, so malformed signatures are 400 and a syntactically valid mismatch remains 401 without parsing JSON.
- Review verification: the new red command produced 10 failures and 3 passes; its green rerun produced 13 passes. The current store/normalizer/webhook focused suite has 93 passing tests; `make events-test`, `make lint`, `make typecheck`, and `make check` passed.
