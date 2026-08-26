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

## Review revision — two-service operations

- The examples now use one long-lived `agent-session-events` identity for webhook delivery and both polling loops. It shares `/etc/agent-session/read.env` with repository drivers through `agent-session-readers`; the driver keeps private write and runtime values in its per-instance `0600` environment file.
- The five one-shot webhook and poller service/timer examples were removed. The event daemon joins the database and readers groups, receives its private webhook-secret path, and runs `serve`. The driver remains a timer-owned `Type=oneshot` service.
- `docs/events.md` now opens by explaining why the event daemon and repository driver remain separate. It documents setup, shared-read credentials, migration, diagnosis, manual one-shot poll diagnosis, recovery, and the review-only boundary without a personal operator name.
- Simple English used pragmatic mode with `configuration` as the single configuration noun and `make sure that` as the selected validation phrase. The three longest prose sentences had 20, 16, and 16 words. Searches found no contractions, perfect tenses, banned modals, progressive clauses, semicolons, Latin abbreviations, trailing `if` or `when` conditions, or alternate check/verify/confirm/ensure verbs outside identifiers and examples.
- TDD evidence: the required behavioral RED is unproven. The attempted `uv run pytest -q tests/events/test_examples.py` command could not start because the sandbox denied access to `/Users/lorchard/.cache/uv/sdists-v9/.git`; this was not a test result. The structural tests later passed with `PYTHONPATH=src python3 -m pytest -q tests/events/test_examples.py` (7 passed). `git diff --check` passed. The controller reran `make events-test`, `make driver-test`, `make docs-check`, `make lint`, and `make typecheck` with approved cache access; each exited 0. The event and driver test output was 765 passed and 2 skipped. Docs-check retained its pre-existing explicit `make gate-test` assertion-count skip, lint passed, and typecheck reported no issues in 104 source files. `make check` also exited 0 with 765 passed, 2 skipped, the same documented docs-check skip, and `all checks passed`.

### Review fix round 1

- The manifest now includes `/etc/agent-session` as `root:root` mode `0755`. The example test first failed on its missing `read-environment-directory` role and then passed after the manifest addition.
- The event runbook now requires a long-lived, genuinely read-only PAT. It states that `AGENT_GH_READ_TOKEN_CMD` runs only at startup and can retrieve that PAT but cannot mint an expiring App token. It also names repository and Projects V2 board read access. `docs/usage.md` says the App route remains driver-only.
- The Simple English pragmatic pass did not yet separate every descriptive and procedural passage. The three longest prose sentences have 20, 16, and 16 words. Searches found no listed mechanical violations or alternate validation verbs in prose.
- Review verification: `PYTHONPATH=src python3 -m pytest -q tests/events/test_examples.py` passed 7 tests. `make docs-check` exited 0 with its pre-existing explicit `make gate-test` assertion-count skip. `git diff --check` passed. No service-manager, deployment, GitHub, push, or merge action occurred.

### Review fix round 2

- The runbook now puts the daemon's one-time `_CMD` behavior in its own descriptive paragraph. The PAT instructions now form a procedural paragraph. It also puts daemon-owned polling cadence in a descriptive paragraph and gives the busy-database alternatives explicit conditions.
- The changed passages follow the pragmatic Simple English audit. The task report no longer says that the first rewrite separated every passage.
- `make docs-check` exited 0 with its pre-existing explicit `make gate-test` assertion-count skip. `git diff --check` passed. No broad suite ran for this prose-only correction.

### Whole-branch review revision

- The system read credential is now the default for driver and event reads. Each repository or Projects mutation supplies its private credential at the mutation boundary.
- The event daemon resolves the owner of the shared PAT once at startup. Reaction polling uses that login and does not read private driver configuration.
- Plain installation webhooks can omit `repositories`. Installation claims are diagnostic-only and do not call the App-token-only `/installation/repositories` endpoint.
- Runtime open and readiness use the same complete schema-shape comparison as `doctor`. This comparison includes columns, foreign keys, and indexes.
- A revision claim now creates durable issue targets for every unselected actionable sibling. Acknowledgement of the source claim does not erase that work.
- Configuration loading rejects duplicate board owner and number pairs. The owner comparison is case-insensitive.
- Daemon shutdown supplies a thread-safe stop signal to each pass. Pollers and GitHub reads inspect it before each new source or subprocess.
- Webhook outcomes now use the allowlisted JSON emitter. Records include safe delivery fields, HTTP status, invalidation count, and elapsed time.
- The runbook now requires JSON webhook bodies and names all five retired preview units. Current documentation uses the term `full-scan mode`.
- Group 1 is commit `b39ad26`. Its 316-test focus, Ruff, mypy, and diff checks passed.
- Group 2 is commit `07c93de`. A 300-test event focus, Ruff, mypy, and diff checks passed.
- Two unchanged set-group-ID tests fail in this sandbox. The file system removes the set-group-ID bit, so the group-shared path precondition is absent.
- The seven example tests passed. `make docs-check` passed with its documented nested gate-count skip.
- The Simple English pass used pragmatic mode and the term `configuration`. The three longest prose sentences contain 20, 18, and 17 words.
- The mechanical scan found no contractions, banned modals, perfect tenses, progressive clauses, semicolons, Latin abbreviations, or alternate validation verbs in prose.
- No deployment, service-manager action, Caddy reload, GitHub mutation, push, merge, or review reply occurred.

### Whole-branch fix and controller verification

- The whole-branch investigation validated all nine Important findings. The fixes establish the
  shared read credential as the system default with explicit mutation boundaries, resolve the PAT
  owner for reaction filtering, and keep plain installation targets diagnostic-only. They also
  strengthen runtime schema validation, preserve revision siblings through acknowledgement,
  reject duplicate boards, bound shutdown between calls, and emit safe structured webhook logs.
- The operator fixes require JSON webhook bodies, name all five retired preview units, and use
  `full-scan mode` for the supported fallback. This plan reconciliation resolves the third Minor
  finding without manufacturing evidence for the unproven Task 8 behavioral RED.
- The credential changes are commit `b39ad26` (`Review: enforce event credential boundaries`). The
  runtime changes are `07c93de` (`Review: close event runtime gaps`). The operations guidance is
  `39c2ca3` (`Review: finish event operations guidance`).
- Verification round 1 found ten direct driver regressions plus the nested gate's propagated
  failure. Seven discussion-manager fakes rejected an unnecessary `env=None`; three workspace
  integration lock fakes did not model the new read and write environments. Commit `23ccb2a`
  (`Review: preserve credential boundary compatibility`) omits the keyword only when no explicit
  environment exists and makes the integration doubles assert the credential split across lock
  acquisition, attempt tracking, and release. The focused GREEN run passed 11 tests, and the full
  driver suite passed 770 with 2 documented skips.
- On head `23ccb2a`, the controller ran
  `make events-test driver-test docs-check lint typecheck`; it exited 0. The driver suite passed 770
  tests with 2 documented skips. Docs-check passed with its explicit nested `make gate-test`
  assertion-count skip. Ruff passed, and mypy found no issues in 104 source files.
- The controller also ran `make check`; it exited 0 with 770 passed, 2 documented skips, and
  `all checks passed`.
- The Task 8 behavioral RED command remains unchecked. Its sandbox-denied uv-cache attempt never
  started pytest and therefore proves no behavior. Owner-review replies and the reviewed-commit
  push also remain unchecked. No deployment, service-manager action, Caddy reload, GitHub mutation,
  merge, or infrastructure write occurred during this fix pass.
- These results support evidence reconciliation. They do not constitute the final whole-branch
  re-review.

### Whole-branch fix re-review round 1

- The re-review left two Important boundaries open. The agent child stripped the driver-prefixed
  GitHub App variables but retained the three supported `GH_APP_*` aliases. GraphQL pagination
  used one `gh api graphql --paginate --slurp` process, so shutdown had no boundary between the
  internal page requests.
- The credential regression names all six accepted App spellings independently. RED passed the
  three `DRIVER_GH_APP_*` cases and failed the three `GH_APP_*` cases. The child environment now
  strips all six while driver resolution retains both spellings.
- GraphQL pagination now runs one bounded subprocess per page. It keeps the six typed operation
  documents unchanged, maps each operation to its response connection without field-substring
  dispatch, passes each next cursor explicitly, and checks the stop signal through `_read`
  immediately before every page subprocess. One-shot calls still fetch every page.
- The combined RED was `...FFFF`: three leaked legacy aliases and one project-pagination shutdown
  case that returned incomplete pagination instead of stopping. The focused GREEN was `.......`.
  The credential, resolver/driver, Projects, reactions, and daemon focus then passed 180 tests.
- `make driver-test` passed 776 tests with 2 documented skips. `make events-test` reached 301 passes
  and only the same two sandbox set-group-ID failures. Excluding only those two environment cases,
  all remaining 301 event tests passed. Ruff passed, mypy found no issues in 104 source files, and
  `git diff --check` passed.
- The fix is commit `7352a2e` (`Review: finish credential and shutdown boundaries`). On that head,
  the controller's event, driver, documentation, lint, and typecheck matrix exited 0. The driver
  suite passed 776 tests with 2 documented skips; docs-check, Ruff, and mypy were green.
- A fresh scoped re-review approved both the App-alias stripping and page-by-page GraphQL
  pagination with no new findings. Owner-review replies, push, deployment, service-manager actions,
  Caddy reload, GitHub mutation, merge, and infrastructure changes remain unperformed.
