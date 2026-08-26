# Event-driven invalidation queue with polling fallbacks

**Goal:** Let timer-driven agent-session drivers reconcile recent GitHub changes first, while preserving live GitHub queries and full scans as the authority and correctness fallback.

## Current state

The driver is a one-shot process. Each run queries live issues, Projects V2 items, pull requests, reviews, checks, comments, and reactions, then sends plain data to the priority router (`src/agent_sessions/driver/lifecycle.py:256`, `src/agent_sessions/driver/lifecycle.py:763`, `src/agent_sessions/driver/router.py:23`). It writes run provenance, park state, and an inflight recovery marker, but keeps no durable event queue (`src/agent_sessions/driver/lifecycle.py:407`, `src/agent_sessions/driver/lifecycle.py:1099`). Git-ref issue locks already prevent duplicate agent work (`src/agent_sessions/driver/locks.py:30`).

The reconciler already separates pure event decisions from polling. It defines plain event and decision records, parses a narrow webhook-shaped payload, synthesizes equivalent events from polled state, and exposes a proof-oriented webhook runner (`src/agent_sessions/driver/reconciler.py:19`, `src/agent_sessions/driver/reconciler.py:153`, `src/agent_sessions/driver/reconciler.py:206`, `src/agent_sessions/driver/reconciler.py:260`). No production webhook host or persistent webhook path calls it.

GitHub App credentials can mint scoped installation tokens (`src/agent_sessions/driver/credentials.py:158`, `src/agent_sessions/driver/credentials.py:216`). The agent and driver already share one logical repository-read credential. Extend that read identity to every event source. Keep driver-only repository and Project mutation credentials separate.

## Inventory conclusion

The [GitHub webhook catalog](https://docs.github.com/en/webhooks/webhook-events-and-payloads) was reviewed for GitHub App availability and this driver's routing inputs on 2026-08-21.

Subscribe to this minimal workflow set:

- `issues`, `issue_comment`
- `pull_request`, `pull_request_review`, `pull_request_review_comment`, `pull_request_review_thread`
- `check_run`, `check_suite`, `status`
- `ping`, `meta`, `installation`, `installation_repositories`, `installation_target`

The first three groups can invalidate live issue, PR, or CI state. The last group supports health and installation topology; it must never start agent work by itself. Retain verified unknown events and actions for diagnosis, but do not create dirty targets from them.

Do not subscribe to broader repository, ref, deployment, security, organization, discussion, package, sponsorship, marketplace, or ecosystem events in v1. They do not change current routing inputs. `workflow_run` and `workflow_job` duplicate the selected check/status signals for this workflow. Defer `push` until a concrete routing transition needs it.

Two relevant changes lack usable GitHub App webhooks:

- User-owned Projects V2 changes. The catalog's Projects V2 events are not available to this App endpoint.
- Reactions. GitHub exposes reactions through its APIs but defines no reaction webhook event. A thumbs-up approval can therefore change routing without producing a delivery.

Cover both gaps with narrow scheduled pollers. Full scans remain the catch-all for failed deliveries, missed signals, and future unknown gaps.

## Desired end state

```text
GitHub webhooks ──────────┐
Projects V2 poll loop ────┼── event daemon ──> SQLite ──> one-shot drivers
Approval reaction loop ───┘                       │       hints first
                                                 └────── full-scan fallback
```

All processes run on one host and share a SQLite database on local disk. One long-running event daemon verifies and enqueues webhooks and runs the Projects and reaction pollers from in-process timers. Per-repository drivers remain separate one-shot processes on their own timers and may overlap. The event daemon never invokes an agent or writes to GitHub.

GitHub remains authoritative. Every claimed hint causes a fresh GitHub query before the router decides what to do. The event payload supplies identity and diagnostic context, never current labels, review status, check conclusions, project fields, or eligibility.

The event system is additive:

- With no events database configured, the driver preserves today's pull/query behavior.
- With a healthy database, the driver reconciles dirty targets before scheduled scans.
- Missed events are recovered by quiet-period and hard-deadline full scans.
- If a configured database is unavailable or incompatible, the driver logs degraded mode and performs its full scan. The event daemon fails readiness instead of claiming persistence.

## Process and API design

Add one `agent-session-events` executable with these subcommands:

- `serve`
- `poll-projects`
- `poll-reactions`
- `doctor`
- `queue-status` with human and JSON output
- `migrate`
- `prune`

Reserve `repair-deliveries` for a follow-up.

Use FastAPI with Uvicorn. Disable OpenAPI, Swagger, and ReDoc routes. Run one Uvicorn worker behind Caddy. Keep the request handler independent of socket startup so tests can call the ASGI app directly.

Expose:

- `POST /github/webhook`
- `GET /healthz`
- `GET /readyz`

The webhook endpoint must:

1. Stream and enforce the configured body limit.
2. Require `X-GitHub-Delivery`, `X-GitHub-Event`, and `X-Hub-Signature-256`.
3. Validate HMAC-SHA256 over the exact bytes with constant-time comparison before JSON parsing.
4. Persist the delivery, invalidations, and dirty-target generations in one short transaction.
5. Return `202` only after commit.

Duplicate GUIDs return success without new invalidations. Bad signatures return `401`; malformed input returns `400`; oversized bodies return `413`; transient database failures return `503`. In-process receiver writes are serialized. SQLite arbitrates receiver writes against short poller and driver transactions.

The event daemon holds the webhook secret and the same read-only GitHub credential used by driver reconciliation and agent subprocesses. It holds no repository-write or Project-write credential. Caddy exposes only the webhook route; health endpoints may remain loopback-only.

## SQLite contract

Hide SQL behind a narrow `QueueStore`. The driver uses claim, acknowledge, retry, scan-clock, and reaction-watch operations; it does not query the delivery ledger directly. This keeps a future private queue service possible without adding HTTP in v1.

Use versioned migrations, foreign keys, WAL mode, a busy timeout shorter than GitHub's webhook response deadline, local-disk storage, and restrictive file permissions. Never hold a transaction during a GitHub request or agent run.

The logical records are:

- `webhook_deliveries`: immutable verified payloads, unique by delivery GUID, with disposition and bounded retention.
- `invalidations`: immutable normalized hints from a webhook or synthetic poll observation. One source event may create several rows.
- `dirty_targets`: one mutable row per target, with generation, first/last seen times, lease, retry, and error fields.
- `project_items`: the last complete routing projection for configured Projects V2 items.
- `poll_watches`: active approval predicates and their last observed value.
- `poller_state`: source-specific leases and last-success metadata for boards and reaction polling.
- `repository_state`: stable repository identity, installation metadata, hint and scan clocks, and scan leases.

Key every repository-scoped record by GitHub repository ID and index it for per-repository claims. Store owner/name for diagnostics only. A TOML allowlist defines repositories the driver may process. Record deliveries for other installed repositories with an ignored disposition; never launch work for them.

Enqueueing inserts the immutable source record, appends normalized invalidations, increments each dirty target's generation, and updates its repository's last-hint clock in one transaction. Pollers call the same invalidation/upsert operation without pretending their observations are webhook deliveries.

## Targets and normalization

| Source | Dirty target |
|---|---|
| `issues` | issue number |
| `issue_comment` | issue number, or PR number for a PR conversation comment |
| `pull_request` and PR review events | PR number |
| `check_run`, `check_suite` | every associated PR; otherwise the head revision |
| `status` | revision SHA |
| Projects V2 membership, Status, or Priority change | issue or PR from the project item |
| Approval predicate change | watched issue |
| Installation lifecycle | installation and explicitly affected allowed repositories |
| `ping`, `meta` | no workflow target |

Target kinds are `issue`, `pull_request`, `revision`, `repository`, and `installation`. Reserve repository targets for events with no narrower identity. Installation targets drive control-plane reconciliation, not agent work.

At consumption time, resolve a PR to current `closingIssuesReferences`; resolve a revision to current PRs with that head SHA. A target with no relevant current object is acknowledged without action. One delivery may invalidate several targets. Several target shapes may converge on one issue; the existing Git-ref issue lock remains the final work exclusion.

## Coalescing and claims

Keep every retained delivery and normalized invalidation immutable. Coalesce only scheduling state: each dirty target has one row and a monotonically increasing generation.

A driver claims a bounded per-repository batch in a short transaction and records the claimed generation. After live reconciliation:

- acknowledge irrelevant targets;
- perform and acknowledge housekeeping-only park/unpark work;
- send actionable targets through the existing priority router;
- retry transient failures with capped backoff;
- release targets blocked by another issue lock.

The driver invokes at most one agent session. It acknowledges the selected target only after the existing inflight marker is durable. It releases other actionable targets for later runs. Acknowledgement deletes a row only when its current generation equals the claimed generation; a concurrent invalidation therefore survives.

Expired leases recover crashed consumers. A new generation resets target backoff. V1 has no dead-letter state because one failing target cannot block other claims and full scans provide another recovery path.

Use a repository scan lease to prevent overlapping full scans. A hard maximum scan age takes precedence over dirty targets. Otherwise, scan only when no target is immediately eligible, the repository has been quiet for its configured interval, and the normal scan interval has elapsed. A full scan does not bulk-delete dirty rows because GitHub's scan is not an atomic snapshot.

## Pollers

`poll-projects` fetches every page for each configured board outside a transaction. Its first successful fetch establishes a silent baseline. Later successful polls compare only item membership/removal, Status, and Priority. Commit the new snapshot and derived invalidations atomically. Failed, rate-limited, or incomplete fetches preserve the prior snapshot and cannot infer removals. Retain prior coordinates long enough to target a removed item.

`poll-reactions` queries only active approval watches. The driver creates or refreshes a watch when it parks an issue awaiting approval and removes it when that state ends. A conditional watch update emits one invalidation when the approval predicate changes. Full scans repair missing and stale watches.

The event daemon starts one task for each enabled poller. Each task runs immediately, performs one pass through the existing synchronous poller outside the event loop, then waits its configured fixed interval. A task never overlaps itself or catches up missed intervals. Each pass opens its own SQLite connection and retains the source-specific lease, so a duplicate daemon cannot run the same source concurrently. No GitHub request runs inside a SQLite transaction.

A normal source failure is stored and logged, then retried after the interval. It does not stop webhook ingestion or make the daemon unready. An unexpected background-task exit does make `/readyz` fail. Shutdown stops new passes and allows bounded in-flight GitHub requests to finish. The one-shot `poll-projects` and `poll-reactions` commands remain for manual diagnosis and return nonzero without changing observations on failure.

## Configuration, credentials, and operations

Parse a small shared TOML file with `tomllib`. It contains the SQLite path, repository ID/name allowlist, configured Projects V2 boards, payload and retention limits, scan policy, and a strict `[polling]` table with positive `projects_interval_seconds` and `reactions_interval_seconds` values. It does not duplicate driver repository paths, workspaces, backend, model, or budget settings. Secrets come from protected files or service credentials, never TOML or command arguments.

Use one system-wide read credential:

- `serve`, `poll-projects`, and `poll-reactions` use `AGENT_GH_READ_TOKEN` or `AGENT_GH_READ_TOKEN_CMD`.
- driver reconciliation and the agent subprocess use the same logical read credential.
- `DRIVER_GH_WRITE_TOKEN` remains driver-only for repository mutations.
- `DRIVER_GH_BOARD_TOKEN` remains driver-only for Projects V2 mutations and is never loaded by an event poller.

The event daemon requires a long-lived, genuinely read-only PAT. A command-backed value may retrieve that PAT from protected storage, but it is not an App-token refresh mechanism. Direct GitHub App token minting remains available to the driver and is not added to the long-running daemon. `doctor` resolves the shared read credential once and proves that it can read every configured repository and Project. It never substitutes the Project-write credential for a failed read probe.

`doctor` validates configuration, database mode and integrity, schema compatibility, repository identity, board access, and credential capability without writing GitHub state. `queue-status` reports backlog state and age, leases/backoff, latest webhook and poll success, scan age, watches, and recent errors. `migrate` applies explicit versioned migrations while services are stopped. Processes refuse to write an incompatible schema. `prune` removes expired raw deliveries and invalidation history and checkpoints WAL; it never age-prunes dirty targets, watches, snapshots, or scan state.

Emit structured logs to stdout/stderr for journald. Include delivery GUID, event/action, repository ID, disposition, and elapsed time. Exclude payload bodies, comment text, signatures, and tokens.

## Patterns to follow

- Keep GitHub I/O outside pure routing logic as `reconciler.py` and `router.py` do (`src/agent_sessions/driver/reconciler.py:52`, `src/agent_sessions/driver/router.py:23`).
- Reuse the polling adapter's live-state decision path rather than adding payload-authoritative decisions (`src/agent_sessions/driver/reconciler.py:206`).
- Preserve the existing inflight-before-invocation boundary (`src/agent_sessions/driver/lifecycle.py:1099`).
- Preserve Git-ref issue locks as the final distributed work lock (`src/agent_sessions/driver/locks.py:30`).
- Extend the current CLI/environment configuration style without changing unrelated driver settings (`src/agent_sessions/driver/lifecycle.py:256`).
- Reuse the existing literal and command-backed read credential resolution without introducing resident App-token refresh logic (`src/agent_sessions/driver/credentials.py:158`).

## Verification and acceptance

Add `make events-test`; include it in `make check`. Use real temporary SQLite databases rather than mocked stores. Add `httpx` to development dependencies for FastAPI tests.

`make events-test` must verify:

- signature validation over exact request bytes, body limits, malformed input, duplicate GUIDs, readiness, disabled documentation routes, and commit-before-`202` behavior;
- immediate fixed-delay poll scheduling, no self-overlap, independent SQLite connections, transient source failure recovery, unexpected task-death readiness, and graceful shutdown;
- one shared read credential across both event pollers, with no event access to repository-write or Project-write credentials;
- generation races, conditional acknowledgement, simultaneous driver claims, lease expiry, retry backoff, full-scan exclusion, and database-unavailable degradation;
- every selected event-to-target mapping, one-to-many check events, revision resolution, and ignored unknown/unconfigured deliveries;
- silent Projects baseline, add/remove and Status/Priority diffs, complete pagination, and snapshot preservation on failure;
- approval predicate changes, conditional emission, and concurrent reaction pollers;
- scan scheduling truth tables and source-specific leases;
- an ASGI-to-SQLite-to-driver-claim integration path for both a signed webhook and a synthetic poll observation;
- fresh schema creation, forward migration, inspection, and pruning behavior.

Every GraphQL document added by this issue has a named operation and an explicit operation type. The strong GitHub fake dispatches those requests by exact operation name rather than matching selected fields in the query text. Transaction tests preserve rollback and exception translation while allowing the transaction context manager to use one guarded path.

`make driver-test` must retain the existing routing and recovery behavior. A driver without an events database performs the supported full-scan path without importing or opening the event queue. `make check` must pass before review.

Dependency changes and all shipping `src/**` edits are risk-gated. This issue remains `needs-review` regardless of test results.

## Delivery slices

1. SQLite schema, migrations, `QueueStore`, and inspection commands.
2. FastAPI receiver and normalization.
3. Optional queue-first driver integration and scan scheduling.
4. Projects V2 and approval-reaction pollers.
5. Service examples and an operator runbook.
6. Review revision: combine the event processes, unify all read paths, and simplify the operator topology.

Each slice must remain independently testable. The implementation stops at deploy-ready artifacts and commands.

## What we're not doing

- No authoritative event-driven workflow decisions.
- No immediate driver or agent invocation from webhook arrival.
- No JSONL queue, Redis, hosted broker, remote database, or REST queue service.
- No combined event/driver daemon. The event daemon and write-capable repository driver remain separate.
- No automatic merge or expansion of the write manifest.
- No broad webhook subscription beyond the listed set.
- No general Projects V2 mirror beyond membership, Status, and Priority.
- No general comment or reaction scan; only active approval watches.
- No failed-delivery repair in v1.
- No Prometheus service, dashboard, automated paging, payload replay, dead-letter queue, or automatic corruption repair.
- No Caddy, GitHub App, systemd, homelab, staging, or production deployment without explicit approval.

## Rejected alternatives

- **JSONL queue:** append-only files fit provenance but cannot cleanly provide atomic deduplication, coalescing, claims, leases, or concurrent consumers.
- **Queue REST API in v1:** HTTP changes transport, not driver statefulness, and adds authentication, availability, retry, and versioning costs. Keep `QueueStore` narrow so a private queue service can replace direct SQLite if drivers later leave the host or need an OS-level data boundary.
- **Separate poller services:** rejected after review because they multiply service identities, secret files, timers, and operational paths without protecting a write capability. The combined event daemon holds only the webhook secret and the system read credential. Background GitHub work remains outside the webhook request path.
- **Docker bundle:** rejected because it packages the same service topology instead of simplifying it and introduces a deployment mechanism this issue does not otherwise need.
- **Remote broker or database:** the selected same-host topology does not justify another service.
