## Phase 1 — durable queue core

- Queue state uses immutable delivery/invalidation rows and coalesces only `dirty_targets`; a new generation clears an older lease and backoff, so a stale acknowledgement cannot erase newly observed work.
- Every store operation runs only local SQLite work in a short transaction. Timestamps are normalized at the storage boundary to UTC RFC 3339 strings.
- Migrations are applied in one `BEGIN EXCLUSIVE` transaction without `executescript`, which would implicitly commit and break migration rollback semantics.
- Configuration is deliberately strict and credential-free. It validates only the shared database, retention, scan, repository, and board fields.
- Phase verification: `make events-test` (15 passed), `make lint`, `make typecheck`, and `make check` (721 passed, 2 skipped) all passed on 2026-08-25.
