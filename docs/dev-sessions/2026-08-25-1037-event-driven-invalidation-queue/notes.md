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

## Phase 3 — queue-first driver reconciliation

- The optional events configuration is resolved at preflight but imported/opened only in the configured branch. Legacy runs call the unchanged full scanner exactly once; config/open/readiness/repository failures emit one structured degraded event and use that same path.
- Dirty targets are identities, never state. The live resolver uses the read credential for current issue/PR/revision associations, comments and reactions, unresolved threads, CI/reviews/merge state, while the existing board read supplies current Status/Priority. Existing `router.select` and `PollingAdapter` remain the decision machinery.
- Queue operations stay on either side of live GitHub reads and agent invocation. Claims are bounded; transient reads back off exponentially; irrelevant and housekeeping-only work is acknowledged; actionable non-selected work is released. A PR claim shared by several closing issues remains leased when it is the selected claim.
- The Git-ref issue lock remains the final selection exclusion. The selected queue acknowledgement runs only after the inflight JSON is durable. A newer generation makes the conditional delete a no-op and invocation continues; a database exception removes the marker, releases the Git lock, logs degradation, and performs one legacy selection before any backend starts.
- Hard maximum scan age wins over dirty work. Otherwise claims run first, then a quiet/interval full scan under the repository lease. Successful full scans update the scan clock and deliberately do not bulk-delete dirty targets.
- Approval watches are created only after a fresh label read confirms an agent-driven triage/refine park. Current comment/reaction unpark removes the watch; leased full scans repair missing/stale rows; loop-breaker parks are excluded. Watch failures are logged and never change the recorded run outcome.
- Phase 1's fixed claim value did not carry `retry_count`, but Phase 3's exact exponential formula requires it. `ClaimedTarget.retry_count` therefore gained a backward-compatible default and `claim_targets` now returns the stored count; no schema or transaction semantics changed.
- No facade or reconciler extension was necessary: the facade already re-exports the edited lifecycle functions, and `PollingAdapter` already carries every live PR field needed by the router.
- TDD evidence: scan-policy collection first failed on the absent driver module; resolver/selection collection then failed on absent `QueueRuntime`; lifecycle seams produced 8 focused failures; live thread/reaction/board tests produced 3 focused failures; and the multi-closing-issue test exposed the selected-lease release. Each focused set passed after its minimal implementation.
- Final verification on 2026-08-25: focused Phase 3 tests passed; `make events-test`, `make driver-test`, `make lint`, `make typecheck`, and `make check` all exited 0. The complete check retained its existing explicit gate-test availability skip.

### Review fix round 1

- GitHub read disposition is now deliberately conservative: only an explicit object-read 404 is treated as absence. Authentication, server, transport, malformed JSON, incomplete GraphQL pages, and command-start/lookup failures retry. Current board reads use the same strict path, so board-only eligibility cannot be acknowledged from an empty failure fallback.
- The legacy selector still presents an empty selection after an issue-list failure, but now also returns an internal completeness bit. Queue scan bookkeeping consumes that bit: failed snapshots retain the previous success time and watches and finish the lease as failed.
- Queue exceptions may happen after selection has acquired the Git ref, including duplicate acknowledgement, non-selected release, and `finish_scan`. The main queue-error boundary now releases any current issue ref before the one legacy fallback.
- Attempt labels move only after the post-inflight selected acknowledgement callback succeeds. This preserves successful-run semantics while ensuring a pre-backend database failure cannot consume an attempt that the fallback consumes again.
- Park-label mutation is no longer proof of unpark. Both targeted and full scans re-read current labels and remove/exclude watches only when the park label is actually absent. A new watch reads its timestamp back from the persisted park transition written after classification.
- Explicit `--issue` / `--retry` are manual routing requests, not queue hints. Configured mode therefore performs the legacy authoritative snapshot under a repository scan lease before claiming dirty rows, preserving unrelated hints.
- Target hydration uses GraphQL connection pagination for review threads, parked issue comments and reactions, open PR discovery, and nested closing references. Every page must end with `hasNextPage: false`; otherwise resolution retries.
- Review-fix verification on 2026-08-25: focused events/scan and driver/full-loop suites passed; `make events-test`, `make driver-test`, `make lint`, `make typecheck`, `make check`, and `git diff --check` exited 0. `make check` reported 743 passed and 2 skipped (the documented gate-test availability skip remains explicit).

### Review fix round 2

- A successful capped CLI read is not necessarily a complete read. The unchanged legacy scan still consumes and displays up to 500 issues, but event-mode scan bookkeeping treats exactly 500 as incomplete. It finishes the lease failed, preserves the prior success clock and watches, discards the partial selection, and releases any Git ref acquired while producing it.
- Authoritative unpark confirmation now requires a JSON object containing a list of label objects whose `name` values are strings. Missing or malformed shapes raise into the existing watch-degradation boundary, so only a valid list that lacks the park label can remove a watch.
- `gh pr view --json closingIssuesReferences` remains useful for the PR snapshot but not for completeness. `_pr()` now replaces that field with the fully paginated GraphQL connection before resolving issues or routing; revision hydration uses the same path. Missing page metadata and page-command failures are transient.
- TDD evidence: the 499/500 scan boundary produced 1 pass and 1 expected failure before the fix; targeted and full malformed-label tables each produced 5 expected failures and 1 existing pass; direct PR/revision pagination plus retry disposition produced 4 expected failures. Their GREEN reruns produced 4 scan passes, 8 targeted label passes, 7 full-scan label passes, and 4 pagination passes.
- Round-two verification on 2026-08-25: focused events/scan and driver/full-loop suites, `make events-test`, `make driver-test`, `make lint`, `make typecheck`, `make check`, and `git diff --check` exited 0. The full check reported 751 passed and 2 skipped, retaining the explicit gate-test availability skip.

## Phase 4 — Projects and approval-reaction pollers

- Scoped credential entry points reuse the existing no-shell token-command and GitHub App helpers but inspect only their own credential family. The board path has no fallback; the reaction path can mint only the existing read-permission installation token.
- Projects use GraphQL `--paginate --slurp` and validate every item page plus terminal `pageInfo`; nested field pagination must already be complete. Supported issue/PR items require stable node, repository, content, Status, and Priority projection data before the snapshot can commit.
- `poller_state.last_success_at` distinguishes a never-fetched board from an established empty baseline. Snapshot replacement and its coalesced invalidations remain one transaction; failure records an error without changing the prior snapshot.
- Approval reads are grouped by configured repository and query only active watch issue numbers. Comment and reaction connections must be complete before any watch observation changes; only non-bot comments or human `THUMBS_UP` reactions strictly after `parked_at` satisfy the predicate.
- A changed watch observation now updates the watch and enqueues its issue invalidation in the same SQLite transaction. Re-parking resets the observation baseline, and the stored `parked_at` participates in the conditional update so a stale poll cannot overwrite a newer watch.
- Source leases and synthetic provenance use `projects:<owner>/<number>` and `reactions:<repository-id>`. The CLI commands resolve only their scoped credential, invoke one pass, log aggregate counts, and return; cadence remains external.
- TDD evidence: scoped credential RED produced five missing-API failures; Projects and reactions each failed collection on their absent APIs; the CLI RED left only its two absent composition seams; the project source-key assertion then caught the inherited bare-board provenance. Each focused suite passed after its corresponding minimal implementation.
- Final verification on 2026-08-25: the focused credential/project/reaction suite passed 92 tests; `make events-test` passed 180 tests; `make driver-test` passed 758 with 2 skipped; `make lint`, `make typecheck`, `make check`, and `git diff --check` exited 0. The complete check reported 758 passed and 2 skipped, retaining the explicit gate-test availability skip.

### Review fix round 1

- Scoped credential commands reuse the legacy command executor but request category-only errors. The broad driver resolution path retains its existing diagnostics; scoped command output and App-mint exception content cannot reach resolver text, traceback rendering, or CLI logs.
- Approval observations compare all fetched watch state, not just identity and park time. A same-park update through another connection makes the stale write a no-op, preventing both value reversal and `last_checked_at` regression.
- The current board allowlist applies symmetrically to the prior and fetched projections. Rows from repositories removed from board configuration disappear from storage without synthesizing removals; currently configured repositories retain normal removal behavior.
- Projects validation distinguishes the four documented item enum values: Issue and PullRequest project normally, DraftIssue is ignored only with `DraftIssue` content, and REDACTED is ignored only with null content. Unknown/missing/non-string types, incomplete nested fields, and missing or mistyped cursor members fail the complete fetch.
- Poller writes now obtain a fresh post-fetch time and check source owner plus unexpired lease in the same transaction as snapshot replacement or watch CAS. Reaction batches resample that clock for every watch transaction. A worker that loses or outlives its lease records no stale mutation; conditional `finish_poller` cannot disturb a successor's lease.
- TDD evidence: credential leakage produced four expected failures plus traceback-chain and empty-App metadata failures; watch CAS produced two failures; current allowlist produced one; malformed Projects produced seven while valid unsupported data stayed green; real-store lease handoff produced two, removing only the expiry predicate made both bare-expiry regressions fail, and a two-watch batch exposed a reused pre-expiry timestamp. Each focused case passed after its narrow fix.
- Round-one verification on 2026-08-25: the focused credential/project/reaction suite passed 118 cases; `make events-test` passed 199; `make driver-test` and `make check` passed 765 with 2 skipped; `make lint`, `make typecheck`, `make docs-check`, and `git diff --check` exited 0. The explicit gate-test availability skip remains labeled as unverified rather than a pass.
