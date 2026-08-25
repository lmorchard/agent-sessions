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

## Phase 5 — event queue operations

- `doctor` now returns structured pass, fail, warn, and skip probes for strict configuration, private database paths, read-only SQLite health, exact schema compatibility, queue clocks, repository identity, board fields, scoped credentials, and the protected webhook-secret file. It opens SQLite with `mode=ro`, issues only GitHub repository and project reads, and omits command output and credential values from diagnostics.
- Missing webhook, poll, or scan success clocks remain warnings rather than successes. Missing credentials skip the dependent capability checks with a concrete remedy. Any failed probe makes the command exit 1; warnings and skips remain nonfatal so an operator can inspect all independent boundaries in one pass.
- `queue-status` adds delivery, hint, and scan-start ages to JSON and includes delivery age in its concise human summary. Unknown clocks remain `null`, `unknown`, or `never`.
- Parsed example tests validate the shared TOML through the production loader, parse strict systemd units and command vectors, and parse the Caddy block tree. The examples keep the receiver on loopback with one Uvicorn worker, make pollers one-shot while timers own cadence, load one scoped credential environment per service, pass the optional event config to drivers, and publish only `/github/webhook`.
- The operator runbook covers local permissions, GitHub App reads and subscriptions, separate Projects credentials, stopped-service migration and backup order, readiness and degraded driver behavior, timers, status interpretation, pruning, recovery, and the non-deployment review boundary. README and usage documentation only point to that canonical guide.
- TDD evidence: the first doctor/status RED produced 14 expected failures and 12 passes; the CLI error-path RED produced 2 expected failures and 26 passes. The example RED produced 8 expected failures for seven absent artifacts and the missing one-worker argument. GREEN produced 28 operations passes and 7 example passes; the combined example/worker regression passed 8 cases.
- Final verification on 2026-08-25: all eight CLI help surfaces exited 0; `make events-test` passed 227 collected tests; `make driver-test` passed 765 with 2 skipped; Ruff passed; mypy found no issues in 102 source files; `make docs-check` and `make check` exited 0. Docs-check still labels its nested gate-test assertion-count probe as skipped, while the independently run driver suite verifies the gate tests.
- No deployment, service-manager action, Caddy reload, GitHub App mutation, push, or pull-request action occurred. The manual review boxes remain open for Les, including the required needs-review classification for dependency, shipping source, lifecycle, and credential changes.

### Review fix round 1

- Every SQLite client in the example topology now runs as `agent-session-driver`, matching the owner-only database directory and file modes. The driver unit also names its repository, state, and workspace paths in both its command and `ReadWritePaths`, so `ProtectSystem=strict` permits its required writes.
- Strict TOML loading converts wrong database, repository-array, and board-array types into actionable `ValueError` diagnostics. Both `doctor` and the other CLI commands exit cleanly without tracebacks or credential disclosure.
- The read-only schema probe now validates expected table columns, foreign keys, and named index columns as well as migration versions. Damage tests remove `project_items`, `invalidations`, and a required index and confirm that diagnosis leaves `sqlite_master` unchanged.
- Projects field diagnosis requests up to 1,000 fields and compares `totalCount` with the returned list before asserting that Status or Priority is missing. Malformed queue clocks produce a non-disclosing failed probe while independent GitHub reads continue.
- The runbook now defines the common effective user, file modes, writable driver paths, accepted literal and command-backed credential variables, bot-login metadata, separated-environment doctor runs, and reaction-instance scope. Its status sample uses a schema-version placeholder.
- TDD evidence: the focused review RED produced 13 expected failures among 60 cases. The unchanged command passed all 60 after implementation; the operations/example subset passed 44. Review verification passed 239 event tests, all eight CLI help surfaces, Ruff, mypy over 102 source files, docs-check, and the full check with 765 passing and 2 skipped tests.
- No deployment, service-manager action, Caddy reload, GitHub App mutation, push, or pull-request action occurred during the review fix.

### Review fix round 2

- The common-UID topology from round 1 made SQLite writable but also let the public receiver read every same-owner credential file. The corrected examples use separate webhook, Projects, reactions, and driver users with private primary groups. Only the supplementary `agent-session-events-db` group is shared.
- A parsed permission manifest confines the database group to the setgid `2770` database directory and `0660` database file. Every environment, webhook secret, and App key remains `0600`, owned by its service user and private group; the database group has no credential-file read bit.
- Queue migration detects a `2770` setgid, group-writable, non-world-accessible parent and creates or resets its database to `0660`; owner-only directories retain `0600`. Every queue unit sets `UMask=0007` so SQLite sidecar files inherit usable group modes.
- Database path probes accept exact owner-only access or complete access through one of the caller's effective groups. They fail on world access, partial group modes, and inactive groups. The webhook secret still requires the receiver EUID and owner-only mode.
- The runbook now names all four users, private groups, the database group, exact directory/file ownership and modes, migration EUID and umask, and four separately scoped doctor runs.
- TDD evidence: the five-case focused RED produced four expected failures and one existing pass; the unchanged GREEN command passed all five in 1.88 seconds. The complete store/operations/example focus passed 65, and the required operations/example subset passed 47.
- Round-two verification on 2026-08-25: `make events-test` passed 243 cases; Ruff passed; mypy found no issues in 102 source files; docs-check exited 0 with its existing explicit nested gate-count skip; and `make check` passed 765 with 2 skips.
- No deployment, service-manager action, Caddy reload, GitHub App mutation, push, or pull-request action occurred during round 2.

### Whole-branch review fix

- App-minted read tokens now request Checks and Commit statuses alongside the existing read surfaces. `doctor` discovers one repository commit and exercises check-run and combined-status reads; empty repositories skip both probes, and denied reads fail without exposing the response.
- Control-plane normalization runs before the repository requirement. Genuine repository-less installation families, ping, and meta deliveries remain diagnostic records. Installation targets come only from configured repositories that share the payload's installation ID; repository targets also require an explicit affected-repository entry.
- When one PR claim resolves to several actionable closing issues, selection creates durable dirty targets for every unselected sibling before the source claim can be acknowledged. Coalescing advances generations and invalidates stale leases, so a concurrent older claim cannot delete the sibling.
- Database diagnosis now requires set-group-ID on group-shared directories, validates existing WAL and SHM ownership and modes, and inspects a temporary snapshot without creating source sidecars. Schema diagnosis derives complete column, foreign-key, and index metadata from the shipped migrations, including primary-key and unique-index shape.
- Retention overrides accept only positive integers. Migration `003_scan_errors.sql` stores the latest failed full-scan error without advancing its success clock; a later successful scan clears the error. Queue status exposes repository scan errors and includes them in recent errors.
- Focused TDD evidence: permission scope failed 1 case; capability probes failed 3; repository-less normalization failed 15 while 49 existing cases passed; sibling durability failed 2; path diagnosis failed 5; schema metadata failed 4; retention parsing failed 4; and scan-error persistence failed 1 while its stale-lease guard passed. The combined GREEN focus passed 88 cases.
- Component verification passed `make events-test` with 265 cases and `make driver-test` with 765 passed and 2 skipped. Ruff, mypy over 102 source files, docs-check, all eight CLI help surfaces, and `make check` also passed. The complete check reported 765 passed and 2 skipped; docs-check retained its explicit nested assertion-count skip.
- No deployment, service-manager action, Caddy reload, GitHub mutation, push, or pull-request action occurred during the whole-branch fix.

### Whole-branch scoped re-review

- The first snapshot implementation still opened the source database with SQLite when a WAL or SHM file existed. SQLite created a missing source SHM and changed lock bytes and timestamps in an existing SHM, violating doctor's read-only contract.
- Doctor now copies the source database and every existing WAL or SHM file into a private temporary directory with matching basenames before any SQLite open. All SQLite reads target that copied set. Source path, setgid, group, and mode probes still run before the copy; cleanup remains under `TemporaryDirectory`.
- TDD evidence: the WAL-only source test failed because doctor created a source SHM; the complete source-set test failed because doctor changed the existing SHM's bytes and modification time. GREEN passed both cases plus the existing no-sidecar-creation guard.
- Verification passed the 76-case operations/store focus, `make events-test` with 267 cases, Ruff, mypy over 102 source files, docs-check, and `make check` with 765 passed and 2 skipped. The documentation check retained its explicit nested assertion-count skip.
- No deployment, service-manager action, Caddy reload, GitHub mutation, push, or pull-request action occurred during the scoped re-review fix.

## Final controller acceptance

- Direct source-immutability verification passed all three WAL/SHM guards.
- `make events-test` passed 267 tests; `make driver-test` passed 765 with 2 documented skips; `make check` passed 765 with the same 2 skips and printed `all checks passed`.
- `git diff --check` is clean. The branch contains exactly five Phase commits above `1bb3164`; no deployment, GitHub mutation, push, or PR action occurred.
- Every acceptance category in `spec.md` maps to the named event, driver, poller, operations, or example test suites recorded in `plan.md`.
- At controller acceptance, PR creation and Copilot review were still pending Les's integration choice; the next section records that choice and its result.

## Pull request and Copilot review

- Les chose the PR integration path. The branch was still five commits ahead of the unchanged `origin/main`; PR #275 opened at <https://github.com/lmorchard/agent-sessions/pull/275>. Issue #269 was already in the configured board's `In review` column after linking the PR.
- The standard PR workflow calls for squashing, but this session's accepted plan requires five independently testable Phase commits. The push preserved those five commits.
- Copilot reported that signature syntax accepted uppercase hexadecimal while constant-time comparison used the lowercase header verbatim. The regression first returned 401; normalizing only the validated digest to lowercase made the complete 15-case webhook suite pass.
- Copilot suppressed one note about the empty `research.md`. The issue-first session captured research directly in `spec.md`, so `research.md` now says that explicitly instead of appearing accidental.
- Copilot's review summary correctly keeps the PR in `needs-review` because it changes dependencies, migrations, credentials, shipping source, and lifecycle behavior. No worthwhile review comment was skipped, and no merge or deployment occurred.

## Operator onboarding follow-up

- Les identified that the runbook explained each boundary but did not first explain why several services exist. `docs/events.md` now opens with the data flow, distinguishes the one long-running receiver from timer-driven one-shot jobs, and states that only the repository driver invokes an agent.
- The runbook now compares legacy, webhook-driven, private-polling, and full deployment shapes. It also gives one ordered setup checklist and identifies the existing repository driver timer as the owner of driver cadence.
- Omitting an event producer is documented as a latency trade-off: fresh GitHub reads and scheduled full scans remain authoritative. The configuration section also explains the optional repository `installation_id` used for installation-level webhook mapping.
- Les requested a Simple English pass from the skill installed at `~/.claude/skills/simple-english` (version 1.2.0). The runbook now uses pragmatic mode with strict procedural rules, consistent `configuration` terminology, condition-first commands, and one instruction per sentence.
- The skill self-check found no prose sentence over 20 words and no paragraph over six sentences. Its mechanical scan found no banned modals, contractions, semicolons, perfect tenses, Latin abbreviations, or selected verification synonyms. Code, commands, identifiers, paths, and output samples remained unchanged.
