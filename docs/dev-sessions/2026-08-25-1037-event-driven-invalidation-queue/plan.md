# Event-driven Invalidation Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Add a durable event-invalidation queue that lets one-shot drivers reconcile recent GitHub changes first while retaining live GitHub reads and scheduled full scans as the authority and fallback.

**Architecture:** A new agent_sessions.events package owns configuration, versioned SQLite storage, webhook normalization, pollers, and the agent-session-events CLI. The existing driver receives an optional queue-aware selection wrapper around its current full-scan path; target payloads provide identity only, and existing router/reconciler logic still decides from freshly queried GitHub state. Short SQLite transactions coalesce scheduling state by target generation, while immutable deliveries and invalidations retain diagnostics.

**Tech Stack:** Python 3.11+, sqlite3, tomllib, FastAPI, Uvicorn, httpx, pytest, existing requests/GitHub CLI adapters, systemd and Caddy example configuration.

**Spec:** docs/dev-sessions/2026-08-25-1037-event-driven-invalidation-queue/spec.md

## Global constraints

- GitHub is authoritative. A payload or poll observation may identify work, but may not supply current labels, reviews, CI conclusions, board fields, or eligibility.
- With no events configuration, the driver must execute the current select_queue path unchanged.
- A configured but unavailable or incompatible queue degrades the driver to the current full scan; receivers and pollers instead report not-ready or fail nonzero.
- Every repository-scoped record is keyed by numeric GitHub repository ID. Owner/name is diagnostic metadata.
- Transactions must end before GitHub I/O or an agent invocation begins.
- Webhook delivery, invalidation rows, dirty-target generation changes, and the repository hint clock commit atomically.
- Dirty-target acknowledgement is conditional on the claimed generation. A newer generation must survive.
- The existing distributed Git-ref issue lock remains the final work-exclusion mechanism.
- The existing inflight marker remains durable before agent invocation. A selected queue claim is acknowledged only after that marker is durable.
- The event daemon receives the webhook secret and the same read-only credential used by driver reconciliation and agent subprocesses. Only the driver receives repository-write or Project-write credentials.
- Secrets come from protected files or service credentials, never the shared TOML file or command arguments.
- No service is deployed by this work. Examples and deploy-ready commands stop before Caddy, systemd, GitHub App, homelab, staging, or production changes.
- Each phase is one independently testable commit. Stage named files only; never use a blanket git add.

## Shared file structure and interfaces

The implementation uses focused modules under src/agent_sessions/events:

- models.py — immutable queue, target, repository, claim, watch, projection, and status records shared by all event components.
- config.py — strict TOML parsing and repository/board allowlist lookup; no credential loading.
- migrations/001_queue.sql and migrations/002_pollers.sql — ordered, packaged schema migrations.
- store.py — QueueStore and all SQL transactions; no GitHub or HTTP calls.
- normalize.py — pure webhook payload-to-invalidation mapping.
- webhook.py — HMAC verification and the FastAPI application factory.
- github.py — narrow live GitHub reads for target resolution and pollers.
- driver.py — queue-first claim reconciliation and pure scan-scheduling decisions.
- pollers.py — one-pass Projects and reaction pollers.
- daemon.py — in-process fixed-delay scheduling, per-pass store lifetime, background-task readiness, and graceful shutdown.
- operations.py — doctor, queue status, migrate, and prune command implementations.
- logging.py — one-line structured JSON event logging with an explicit safe-field allowlist.
- cli.py — argparse composition, shared credential wiring, daemon construction, and Uvicorn startup.

The shared model names are fixed here so later phases do not invent aliases:

    TargetKind = Literal[
        "issue", "pull_request", "revision", "repository", "installation"
    ]

    @dataclass(frozen=True)
    class RepositoryIdentity:
        id: int
        owner: str
        name: str
        installation_id: int | None = None

    @dataclass(frozen=True)
    class Invalidation:
        repository_id: int
        target_kind: TargetKind
        target_key: str
        reason: str
        diagnostic: Mapping[str, JSONValue] = field(default_factory=dict)

    @dataclass(frozen=True)
    class ClaimedTarget:
        repository_id: int
        target_kind: TargetKind
        target_key: str
        generation: int
        lease_owner: str

    JSONScalar: TypeAlias = str | int | float | bool | None
    JSONValue: TypeAlias = (
        JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
    )

    @dataclass(frozen=True)
    class ScanPolicy:
        quiet_period: timedelta
        interval: timedelta
        maximum_age: timedelta

    @dataclass(frozen=True)
    class RepositoryConfig:
        identity: RepositoryIdentity

    @dataclass(frozen=True)
    class BoardConfig:
        owner: str
        number: int
        repository_ids: tuple[int, ...]

        @property
        def key(self) -> str:
            return f"{self.owner}/{self.number}"

    @dataclass(frozen=True)
    class EventsConfig:
        database: Path
        busy_timeout_ms: int
        claim_limit: int
        claim_lease: timedelta
        retry_base: timedelta
        retry_maximum: timedelta
        max_body_bytes: int
        delivery_retention: timedelta
        invalidation_retention: timedelta
        scan: ScanPolicy
        repositories: tuple[RepositoryConfig, ...]
        boards: tuple[BoardConfig, ...]

    @dataclass(frozen=True)
    class VerifiedDelivery:
        guid: str
        event_type: str
        action: str
        repository_id: int | None
        raw_body: bytes
        disposition: str
        diagnostic: Mapping[str, JSONValue]

    @dataclass(frozen=True)
    class NormalizedDelivery:
        event_type: str
        action: str
        repository_id: int | None
        disposition: str
        invalidations: tuple[Invalidation, ...]
        diagnostic: Mapping[str, JSONValue]

    @dataclass(frozen=True)
    class EnqueueResult:
        duplicate: bool
        invalidation_count: int

    @dataclass(frozen=True)
    class StoreHealth:
        ready: bool
        schema_version: int | None
        error: str = ""

    @dataclass(frozen=True)
    class ApprovalWatch:
        repository_id: int
        issue_number: int
        predicate: str
        parked_at: datetime
        last_value: bool | None = None
        last_checked_at: datetime | None = None

    @dataclass(frozen=True)
    class ProjectItemProjection:
        board_key: str
        item_node_id: str
        repository_id: int
        content_kind: Literal["issue", "pull_request"]
        content_number: int
        status: str | None
        priority: str | None
        last_seen_at: datetime

    @dataclass(frozen=True)
    class QueueStatus:
        schema_version: int
        backlog_count: int
        oldest_dirty_at: datetime | None
        leased_count: int
        backed_off_count: int
        latest_delivery_at: datetime | None
        repositories: tuple[RepositoryStatus, ...]
        pollers: tuple[PollerStatus, ...]
        watch_count: int
        recent_errors: tuple[str, ...]

    @dataclass(frozen=True)
    class RepositoryStatus:
        repository_id: int
        last_hint_at: datetime | None
        last_scan_started_at: datetime | None
        last_scan_success_at: datetime | None
        scan_lease_owner: str | None
        scan_lease_until: datetime | None

    @dataclass(frozen=True)
    class PollerStatus:
        source_key: str
        last_success_at: datetime | None
        lease_owner: str | None
        lease_until: datetime | None
        last_error: str

    @dataclass(frozen=True)
    class PruneResult:
        deliveries_deleted: int
        invalidations_deleted: int
        checkpoint_busy: int
        checkpoint_log_frames: int
        checkpointed_frames: int

All timestamps cross module boundaries as timezone-aware datetime values and are stored as UTC RFC 3339 strings. SQL helpers perform conversion in one place.

RepositoryStatus and PollerStatus are read-only projections; operations.py is their only consumer. QueueBusy, QueueUnavailable, IncompatibleSchema, and PollFailure are distinct RuntimeError subclasses so the receiver, driver, and one-shot pollers can apply different fallback rules without parsing messages. CommandRunner is the existing callable protocol around subprocess.run used by credentials.py tests.

---

## Task 1: Phase 1 — Durable queue core and inspectable operations

This phase delivers a useful local queue without any HTTP or GitHub dependency: an operator can load configuration, create or migrate a database, enqueue synthetic invalidations, claim/acknowledge/retry them safely, inspect status, and prune immutable history. It establishes the concurrency and generation guarantees on which every later phase depends.

**Files:**

- Create: src/agent_sessions/events/__init__.py — package marker and public model exports.
- Create: src/agent_sessions/events/models.py — records listed in Shared file structure and interfaces.
- Create: src/agent_sessions/events/config.py — strict TOML model and loader.
- Create: src/agent_sessions/events/migrations/001_queue.sql — delivery, invalidation, dirty-target, and repository-state tables.
- Create: src/agent_sessions/events/migrations/002_pollers.sql — project snapshot, approval watch, and poller-state tables.
- Create: src/agent_sessions/events/store.py — QueueStore, migration runner, transactions, claims, leases, watches, snapshots, status, and pruning.
- Create: src/agent_sessions/events/operations.py — migrate, queue-status, database-only doctor, and prune commands.
- Create: src/agent_sessions/events/logging.py — safe structured logging.
- Create: src/agent_sessions/events/cli.py — initial command parser.
- Create: tests/events/__init__.py
- Create: tests/events/conftest.py — real temporary SQLite database and TOML fixtures.
- Create: tests/events/test_config.py
- Create: tests/events/test_store.py
- Create: tests/events/test_operations.py
- Modify: pyproject.toml — register agent-session-events = agent_sessions.events.cli:main and package SQL migrations.
- Modify: Makefile — add events-test, include it in check-parallel, and document it in help.

**Configuration contract:**

The shared TOML has no secrets and no driver workspace/model settings:

    database = "/var/lib/agent-session/events.sqlite3"
    busy_timeout_ms = 3000
    claim_limit = 25
    claim_lease_seconds = 300
    retry_base_seconds = 30
    retry_max_seconds = 1800
    max_body_bytes = 1048576
    delivery_retention_days = 14
    invalidation_retention_days = 30

    [scan]
    quiet_period_seconds = 300
    interval_seconds = 900
    maximum_age_seconds = 3600

    [[repositories]]
    id = 123456
    owner = "lmorchard"
    name = "agent-sessions"
    installation_id = 7890

    [[boards]]
    owner = "lmorchard"
    number = 9
    repository_ids = [123456]

config.load(path: Path) -> EventsConfig rejects unknown keys, duplicate repository IDs or owner/name pairs, relative database paths, non-positive limits, maximum_age_seconds smaller than interval_seconds, boards referencing absent repositories, and owner/name values outside the existing owner/name shape.

Every agent-session-events subcommand accepts --config, defaulting from AGENT_SESSION_EVENTS_CONFIG, and exits 2 when neither is present. The existing driver accepts --events-config with the same environment default; absence means legacy mode. serve alone reads AGENT_SESSION_WEBHOOK_SECRET_FILE.

**SQLite schema:**

- schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL).
- webhook_deliveries(delivery_guid TEXT PRIMARY KEY, event_type TEXT NOT NULL, action TEXT NOT NULL, repository_id INTEGER, received_at TEXT NOT NULL, disposition TEXT NOT NULL, raw_body BLOB NOT NULL, diagnostic_json TEXT NOT NULL).
- invalidations(id INTEGER PRIMARY KEY AUTOINCREMENT, source_kind TEXT NOT NULL, source_key TEXT NOT NULL, repository_id INTEGER NOT NULL, target_kind TEXT NOT NULL, target_key TEXT NOT NULL, observed_at TEXT NOT NULL, diagnostic_json TEXT NOT NULL).
- dirty_targets(repository_id INTEGER NOT NULL, target_kind TEXT NOT NULL, target_key TEXT NOT NULL, generation INTEGER NOT NULL, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, lease_owner TEXT, lease_until TEXT, retry_count INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT, last_error TEXT, PRIMARY KEY(repository_id, target_kind, target_key)).
- repository_state(repository_id INTEGER PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL, installation_id INTEGER, last_hint_at TEXT, last_scan_started_at TEXT, last_scan_success_at TEXT, scan_lease_owner TEXT, scan_lease_until TEXT).
- project_items(board_key TEXT NOT NULL, item_node_id TEXT NOT NULL, repository_id INTEGER NOT NULL, content_kind TEXT NOT NULL, content_number INTEGER NOT NULL, status TEXT, priority TEXT, last_seen_at TEXT NOT NULL, PRIMARY KEY(board_key, item_node_id)).
- poll_watches(repository_id INTEGER NOT NULL, issue_number INTEGER NOT NULL, predicate TEXT NOT NULL, parked_at TEXT NOT NULL, last_value INTEGER, last_checked_at TEXT, PRIMARY KEY(repository_id, issue_number, predicate)).
- poller_state(source_key TEXT PRIMARY KEY, lease_owner TEXT, lease_until TEXT, last_success_at TEXT, last_error TEXT).
- Add foreign keys to repository_state where the referenced record is durable, plus indexes for claim eligibility, retention timestamps, per-repository status, watches, and board snapshots.

QueueStore.migrate first creates the file with mode 0600, enables foreign_keys, WAL, and busy_timeout, acquires BEGIN EXCLUSIVE, applies embedded resources in version order, records each version in the same transaction, and rolls back the entire failing migration. QueueStore.open configures every connection the same way and refuses normal writes unless the database schema equals CURRENT_SCHEMA_VERSION.

**QueueStore interface:**

    class QueueStore:
        @classmethod
        def open(cls, path: Path, *, busy_timeout_ms: int) -> QueueStore: ...

        @classmethod
        def migrate(
            cls, path: Path, *, busy_timeout_ms: int
        ) -> tuple[int, ...]: ...
        def ready(self) -> StoreHealth: ...
        def register_repositories(
            self, repositories: Iterable[RepositoryIdentity]
        ) -> None: ...

        def enqueue_webhook(
            self,
            delivery: VerifiedDelivery,
            invalidations: Iterable[Invalidation],
            *,
            now: datetime,
        ) -> EnqueueResult: ...

        def enqueue_synthetic(
            self,
            source_kind: str,
            source_key: str,
            invalidations: Iterable[Invalidation],
            *,
            now: datetime,
        ) -> int: ...

        def claim_targets(
            self,
            repository_id: int,
            *,
            worker_id: str,
            limit: int,
            lease_until: datetime,
            now: datetime,
        ) -> tuple[ClaimedTarget, ...]: ...

        def acknowledge(self, claim: ClaimedTarget) -> bool: ...
        def retry(
            self,
            claim: ClaimedTarget,
            *,
            error: str,
            next_attempt_at: datetime,
        ) -> bool: ...
        def release(self, claim: ClaimedTarget) -> bool: ...

        def acquire_scan_lease(
            self,
            repository_id: int,
            *,
            worker_id: str,
            lease_until: datetime,
            now: datetime,
        ) -> bool: ...
        def finish_scan(
            self,
            repository_id: int,
            *,
            worker_id: str,
            succeeded: bool,
            now: datetime,
            error: str = "",
        ) -> None: ...

        def acquire_poller_lease(
            self,
            source_key: str,
            *,
            worker_id: str,
            lease_until: datetime,
            now: datetime,
        ) -> bool: ...
        def finish_poller(
            self,
            source_key: str,
            *,
            worker_id: str,
            succeeded: bool,
            now: datetime,
            error: str = "",
        ) -> None: ...

        def upsert_watch(self, watch: ApprovalWatch) -> None: ...
        def remove_watch(self, repository_id: int, issue_number: int) -> None: ...
        def list_watches(self, repository_id: int) -> tuple[ApprovalWatch, ...]: ...
        def record_watch_observation(
            self,
            watch: ApprovalWatch,
            *,
            value: bool,
            observed_at: datetime,
        ) -> bool: ...

        def replace_project_snapshot(
            self,
            board_key: str,
            projections: Iterable[ProjectItemProjection],
            invalidations: Iterable[Invalidation],
            *,
            now: datetime,
        ) -> None: ...

        def status(self, *, now: datetime) -> QueueStatus: ...
        def prune(
            self,
            *,
            deliveries_before: datetime,
            invalidations_before: datetime,
        ) -> PruneResult: ...

enqueue_webhook uses INSERT OR IGNORE for the delivery GUID. If the insert loses, it returns duplicate=True and changes no invalidation, dirty-target, or repository row. A new delivery appends each invalidation and coalesces only dirty_targets:

    INSERT INTO dirty_targets (...)
    VALUES (..., 1, ...)
    ON CONFLICT(repository_id, target_kind, target_key) DO UPDATE SET
        generation = dirty_targets.generation + 1,
        last_seen_at = excluded.last_seen_at,
        lease_owner = NULL,
        lease_until = NULL,
        retry_count = 0,
        next_attempt_at = NULL,
        last_error = NULL

acknowledge deletes only with all five claim coordinates:

    DELETE FROM dirty_targets
    WHERE repository_id = ?
      AND target_kind = ?
      AND target_key = ?
      AND generation = ?
      AND lease_owner = ?

Claims use BEGIN IMMEDIATE and update a bounded set selected by repository, expired/unheld lease, and next_attempt_at. Tests use two QueueStore connections plus a threading barrier to prove simultaneous consumers receive disjoint claims. New generations clear leases and backoff. Expired leases become claimable.

prune deletes only expired webhook_deliveries and invalidations, then runs a passive WAL checkpoint. It never deletes dirty_targets, project_items, poll_watches, poller_state, or repository_state.

queue-status defaults to concise human output and accepts --json. Both formats report backlog count and oldest age, leases/backoff, latest delivery, poll success, scan success/age, watches, schema version, and recent stored errors. Empty values render as unknown or never, never as success.

**TDD and implementation steps:**

- [x] Add failing configuration tests for the accepted TOML and each rejection above. `uv run pytest -q tests/events/test_config.py` initially failed at collection: `ModuleNotFoundError: agent_sessions.events`.
- [x] Implement models.py and config.py minimally. `uv run pytest -q tests/events/test_config.py` → 7 passed.
- [x] Add failing migration tests for a fresh database, a database containing only migration 001, an ahead-of-code schema, a failed migration rollback, foreign-key enforcement, WAL, busy timeout, and mode 0600. Initial store RED was `ModuleNotFoundError: agent_sessions.events.store`.
- [x] Add the two SQL resources and migration runner. `uv run pytest -q tests/events/test_store.py` → 14 passed.
- [x] Add failing QueueStore tests for atomic delivery enqueue, duplicate GUID no-op, generation increments, conditional acknowledgement, simultaneous claims, lease expiry, retry backoff, new-generation backoff reset, scan exclusion, poller exclusion, watches, project snapshot atomicity, and synthetic-source provenance. Initial store RED was `ModuleNotFoundError: agent_sessions.events.store`.
- [x] Implement QueueStore through the fixed interface above with one short transaction per operation. `uv run pytest -q tests/events/test_store.py` → 14 passed.
- [x] Add failing CLI tests for migrate, queue-status human/JSON, doctor schema checks, prune retention boundaries, protected live tables, and incompatible-schema refusal. Initial operations RED was missing `agent_sessions.events.operations`.
- [x] Implement operations.py, logging.py, and the initial cli.py. `uv run pytest -q tests/events/test_operations.py` → 6 passed.
- [x] Add agent-session-events to pyproject.toml and add events-test to Makefile/check-parallel. `make events-test` → 36 passed.
- [x] Run make lint. → `All checks passed!`
- [x] Run make typecheck. → `Success: no issues found in 90 source files`
- [x] Run make check. → exit 0; `all checks passed`.
- [x] Commit only Phase 1 files with message: Phase 1: add the durable invalidation queue core.

**Verification — automated:**

- [x] make events-test passes with real temporary SQLite databases. → 26 passed.
- [x] A deliberate generation race leaves the newer dirty target after acknowledgement of the older claim. `test_new_generation_survives_acknowledgement_of_older_claim`.
- [x] Two simultaneous claims are disjoint and an expired lease is recoverable. `test_two_simultaneous_consumers_receive_disjoint_claims`; `test_claims_and_backoff_are_conditional_and_expired_leases_recover`.
- [x] Fresh creation and migration from schema version 1 both reach CURRENT_SCHEMA_VERSION. `test_migrate_creates_private_wal_foreign_key_database`; `test_migrates_a_database_at_schema_version_one`.
- [x] Pruning removes expired history and preserves every live scheduling table. `test_prune_removes_expired_history_without_touching_live_scheduling_tables`.
- [x] make lint, make typecheck, and make check pass. → lint clean; mypy clean; `make check` exit 0.

**Verification — manual:**

- [x] Review both SQL migrations for constraints and indexes corresponding to every schema field in the spec.
- [x] Review queue-status human output and confirm absent observations say unknown or never. Empty status reports `oldest-age=unknown` and `latest-delivery=never`.
- [x] Confirm the TOML contains no token, secret, driver path, workspace, backend, model, or budget setting.

---

## Task 2: Phase 2 — Verified webhook ingestion and event normalization

This phase delivers an ASGI-to-SQLite ingress path. A signed GitHub delivery is streamed under a hard body limit, verified over exact bytes before parsing, normalized into identity-only targets, and committed before the endpoint returns 202.

**Files:**

- Create: src/agent_sessions/events/normalize.py — selected event/action mapping.
- Create: src/agent_sessions/events/webhook.py — FastAPI application factory and request handling.
- Create: tests/events/test_normalize.py
- Create: tests/events/test_webhook.py
- Create: tests/events/fixtures/ — minimal payloads for every selected event family and one-to-many checks.
- Modify: src/agent_sessions/events/cli.py — add serve.
- Modify: pyproject.toml — add FastAPI and Uvicorn runtime dependencies and httpx development dependency; update uv.lock.
- Modify: Makefile — no new target; events-test already discovers tests/events/test_*.py.

**Normalization contract:**

normalize_delivery(event_type: str, payload: Mapping[str, JSONValue], config: EventsConfig) -> NormalizedDelivery is pure. It reads repository.id first, then owner/name only for diagnostics. An unconfigured repository produces disposition ignored_unconfigured and no targets. Unsupported events and actions produce ignored_unknown_event or ignored_unknown_action and no targets while preserving the verified delivery.

The supported action map is deliberately narrow:

- issues: opened, edited, transferred, deleted, closed, reopened, labeled, unlabeled.
- issue_comment: created, edited, deleted.
- pull_request: opened, edited, closed, reopened, synchronize, converted_to_draft, ready_for_review, review_requested, review_request_removed.
- pull_request_review: submitted, edited, dismissed.
- pull_request_review_comment: created, edited, deleted.
- pull_request_review_thread: resolved, unresolved.
- check_run: created, rerequested, completed, requested_action.
- check_suite: requested, rerequested, completed.
- status: payloads without an action value.
- installation: created, deleted, suspend, unsuspend, new_permissions_accepted.
- installation_repositories: added, removed.
- installation_target: renamed.
- ping: payloads without an action value.
- meta: deleted.

The mapping is:

- issues -> issue number.
- issue_comment -> pull_request when issue.pull_request exists, otherwise issue.
- pull_request and all PR review/comment/thread events -> pull_request number.
- check_run and check_suite -> every pull request in pull_requests; when empty, one revision target from head_sha.
- status -> revision target from sha.
- installation -> installation target plus repository targets for explicitly listed allowed repositories.
- installation_repositories -> installation target plus each allowed repository in repositories_added and repositories_removed.
- installation_target -> installation target only.
- ping and meta -> no workflow target.

Malformed identity for an otherwise supported event returns disposition malformed and no targets; the HTTP layer returns 400 and stores nothing because malformed input is not a verified, usable delivery. Unknown but well-formed events/actions are verified and stored with their ignored disposition.

**ASGI interface:**

    def create_app(
        *,
        config: EventsConfig,
        store: QueueStore,
        webhook_secret: bytes,
    ) -> FastAPI:
        app = FastAPI(
            openapi_url=None,
            docs_url=None,
            redoc_url=None,
        )
        ...
        return app

serve reads AGENT_SESSION_WEBHOOK_SECRET_FILE, requires a regular owner-only file, strips one terminal newline, and rejects an empty secret. It never imports credentials.py or accepts a secret argument.

POST /github/webhook:

1. Requires X-GitHub-Delivery, X-GitHub-Event, and X-Hub-Signature-256.
2. Iterates request.stream(), rejecting as soon as accumulated bytes exceed max_body_bytes.
3. Computes sha256= plus hmac.new(secret, exact_body, hashlib.sha256).hexdigest().
4. Uses hmac.compare_digest before json.loads.
5. Requires a top-level JSON object and calls normalize_delivery.
6. Serializes receiver writes with an asyncio.Lock and calls QueueStore.enqueue_webhook in a worker thread so SQLite cannot block the event loop.
7. Returns 202 only after enqueue_webhook returns from its commit.

Response rules: bad signature 401; absent headers or malformed JSON/payload 400; body too large 413; QueueBusy/QueueUnavailable 503; accepted and duplicate deliveries 202.

GET /healthz returns 200 with status alive without touching SQLite. GET /readyz calls store.ready and returns 200 only for a reachable compatible schema; unavailable, corrupt, or incompatible state returns 503. /openapi.json, /docs, and /redoc return 404.

Structured receiver logs contain only delivery GUID, event, action, repository ID, disposition, invalidation count, HTTP status, and elapsed milliseconds. They never contain the raw body, comment text, signature, or secret.

**TDD and implementation steps:**

- [x] Add failing pure normalization tests for every mapping above, the one-to-many check case, check fallback to revision, issue-comment PR detection, installation filtering, ping/meta no-target behavior, unknown events/actions, malformed identity, and unconfigured repositories.
- [x] Run `uv run pytest -q tests/events/test_normalize.py` and confirm failure: 55 failures, all from the absent `agent_sessions.events.normalize` module.
- [x] Implement normalize.py with immutable NormalizedDelivery output. Re-run tests/events/test_normalize.py: 55 passed; review-fix action-state additions bring the current focused suite to 62 passed.
- [x] Add failing ASGI tests using httpx.ASGITransport for exact-byte HMAC, missing headers, bad signatures, malformed JSON, streamed body limits, duplicate GUIDs, readiness, disabled docs routes, 503 database errors, and commit-before-202.
- [x] For commit-before-202, wrap QueueStore.enqueue_webhook with a barrier and prove the request remains pending until the store call returns.
- [x] Run `uv run pytest -q tests/events/test_webhook.py` and confirm failure: async ASGI test support was absent before the required HTTP dependencies were added.
- [x] Add FastAPI, Uvicorn, and httpx through uv so pyproject.toml and uv.lock change together.
- [x] Implement webhook.py and the serve CLI without starting a socket from create_app.
- [x] Re-run tests/events/test_webhook.py: 9 passed; review-fix signature, malformed-action, and real-lock additions bring the current focused suite to 14 passed.
- [x] Add an integration test that signs a real payload, posts through ASGI, opens a second QueueStore connection, and claims the resulting target.
- [x] Run make events-test: exited 0.
- [x] Run make lint: passed.
- [x] Run make typecheck: passed.
- [x] Run make check: passed (the full gate exited 0).
- [x] Commit only Phase 2 files with message: `Phase 2: add verified webhook ingestion`.

**Verification — automated:**

- [x] Every selected event family reaches the expected target kind and unknown inputs create no dirty target.
- [x] A duplicate delivery returns 202 and does not increment target generation.
- [x] No JSON parser or normalizer is called for a bad signature.
- [x] The ASGI request does not finish before the SQLite commit returns.
- [x] The signed ASGI-to-SQLite-to-claim integration test passes.
- [x] A real second SQLite `BEGIN IMMEDIATE` lock maps to QueueBusy and the ASGI receiver returns 503 after the configured busy timeout.
- [x] Missing action is accepted only for status/ping; present non-string action values are malformed, and unknown strings remain ignored.
- [x] Missing signature is 400; malformed prefix/length/non-hex syntax is 400 before parsing; a valid-form mismatched digest is 401.
- [x] make lint, make typecheck, and make check pass.

**Verification — manual:**

- [x] Review imports and serve startup: webhook.py/cli.py import no credentials resolver and serve reads only AGENT_SESSION_WEBHOOK_SECRET_FILE.
- [x] Review structured log calls: `_log` emits only the specified safe fields and accepts no request-body, signature, or secret argument.
- [x] Review the supported action map against the event inventory captured in the spec; every listed action has a parameterized test.

---

## Task 3: Phase 3 — Queue-first driver reconciliation with full-scan fallback

This phase connects dirty targets to one-shot driver runs. It resolves each claimed identity against live GitHub state, feeds current data through the existing reconciler/router, performs housekeeping, chooses at most one actionable issue, and retains the existing full scan under explicit scan clocks and degraded mode.

**Files:**

- Create: src/agent_sessions/events/github.py — narrow live target resolver and typed GitHub failures.
- Create: src/agent_sessions/events/driver.py — QueueRuntime, target reconciliation, scan scheduling, and claim disposition.
- Create: tests/events/test_driver.py
- Create: tests/events/test_scan_policy.py
- Modify: src/agent_sessions/driver/lifecycle.py:59-93 — add optional events_config_path to RunContext and --events-config/EVENTS_CONFIG parsing only.
- Modify: src/agent_sessions/driver/lifecycle.py:648-823 — expose the legacy full scan unchanged and add queue-aware selection at the caller boundary.
- Modify: src/agent_sessions/driver/lifecycle.py:1059-1179 — add an after_inflight callback invoked immediately after the inflight marker write.
- Modify: src/agent_sessions/driver/lifecycle.py:1187-1393 — maintain approval watches after authoritative park/unpark outcomes.
- Modify: src/agent_sessions/driver/lifecycle.py:1395-end — choose queue-first or legacy selection and finish scan state.
- Modify: src/agent_sessions/driver/agent_session_driver.py — re-export new lifecycle symbols only if existing facade tests require them.
- Modify: src/agent_sessions/driver/reconciler.py — add no I/O; only extend plain event fields if a live-state target needs a value the current PollingAdapter cannot carry.
- Modify: tests/driver/test_driver.py — no-config legacy regression and callback boundary.
- Modify: tests/driver/test_full_loop.py — unchanged legacy routing/recovery assertions plus optional queue path.
- Modify: tests/driver/loop_harness.py — model only the new targeted GitHub reads used by queue tests; keep unhandled-call failure behavior.

**Live resolver interface:**

    class LiveTargetResolver:
        def resolve(
            self,
            repository: RepositoryConfig,
            claim: ClaimedTarget,
        ) -> ResolvedTarget:
            ...

    @dataclass(frozen=True)
    class ResolvedTarget:
        claim: ClaimedTarget
        issues: tuple[dict[str, JSONValue], ...]
        pull_requests: tuple[dict[str, JSONValue], ...]
        board_items: tuple[dict[str, JSONValue], ...]
        irrelevant_reason: str = ""
        control_plane_only: bool = False

All resolver calls use the driver's existing read credential. issue targets fetch that issue plus its current open closing PRs. pull_request targets fetch the current PR and current closingIssuesReferences. revision targets query current PRs whose headRefOid equals the SHA and then their closingIssuesReferences. repository and installation targets refresh configured identity/topology and never become agent candidates. Missing/closed/unrelated objects return irrelevant_reason and are acknowledged without action.

For each resolved issue, build the current inputs router.select already accepts: issue body/labels/state, relevant board Status/Priority, open PR details, park state, attempt labels, current comments/reactions, unresolved threads, CI buckets, reviews, and merge state. Use reconciler.PollingAdapter to synthesize the current PR/comment event and handle_event to derive the same PR phase as polling. The target payload itself supplies none of those values.

**Queue selection interface:**

    @dataclass
    class QueueRuntime:
        config: EventsConfig
        store: QueueStore
        repository: RepositoryConfig

    @dataclass(frozen=True)
    class RepositoryScanState:
        last_hint_at: datetime | None
        last_scan_success_at: datetime | None
        scan_lease_owner: str | None
        scan_lease_until: datetime | None

    @dataclass
    class QueueSelection:
        selection: lifecycle.SelectionResult | None
        selected_claim: ClaimedTarget | None
        acknowledged: tuple[ClaimedTarget, ...]
        released: tuple[ClaimedTarget, ...]
        retried: tuple[ClaimedTarget, ...]
        used_full_scan: bool

    def select_work(
        ctx: lifecycle.RunContext,
        runtime: QueueRuntime | None,
        *,
        now: datetime,
        worker_id: str,
    ) -> QueueSelection:
        ...

Pure scan scheduling is pinned by a truth table:

    def scan_decision(
        *,
        now: datetime,
        state: RepositoryScanState,
        has_immediately_eligible_target: bool,
        policy: ScanPolicy,
    ) -> Literal["hard-deadline", "quiet-period", "not-due"]:
        if state.last_scan_success_at is None:
            return "hard-deadline"
        age = now - state.last_scan_success_at
        if age >= policy.maximum_age:
            return "hard-deadline"
        if has_immediately_eligible_target:
            return "not-due"
        if state.last_hint_at is not None and now - state.last_hint_at < policy.quiet_period:
            return "not-due"
        if age >= policy.interval:
            return "quiet-period"
        return "not-due"

Flow:

1. No --events-config/EVENTS_CONFIG: call the existing select_queue exactly once.
2. Config parse, open, readiness, or repository lookup failure: emit one degraded structured log and call existing select_queue.
3. Hard deadline due: acquire repository scan lease; on success run existing select_queue, record scan completion immediately after the GitHub snapshot/selection returns, and do not bulk-delete dirty targets. If another process owns the scan lease, continue to dirty claims.
4. Otherwise claim a bounded repository batch.
5. Resolve claims outside transactions. Acknowledge irrelevant/control-plane-only targets. Perform and acknowledge housekeeping-only park/unpark changes. Retry transient GitHub failures at min(retry_base * 2 ** retry_count, retry_maximum). There is no retry ceiling or dead-letter state. Release lock-contended or non-selected actionable targets.
6. Send current live data through existing router priority ordering. Acquire the existing Git-ref lock for the chosen issue. Return at most one candidate.
7. When no dirty target is immediately actionable, evaluate the quiet-period scan rule and acquire/run a full scan if due.
8. If an actionable claim is selected, release other actionable claims before invocation. Pass after_inflight=lambda: store.acknowledge(selected_claim) to invoke_agent. If acknowledgement fails because of a newer generation, invocation continues and the newer row survives. If the database call raises, invoke_agent removes the marker it just wrote and propagates before backend invocation; the caller releases the Git-ref lock, logs degraded mode, and falls back to a legacy scan. The expired SQLite lease later recovers the claim.

invoke_agent writes the existing inflight JSON first and calls after_inflight synchronously before run_request_review or agent_runner.run_agent. A test callback asserts the file exists and contains the issue/phase before it is called.

Approval-watch maintenance:

- After an agent-driven triage/refine outcome leaves agent-session:needs-human applied, upsert predicate human_approval_since_park with the authoritative park timestamp.
- When selection removes the park label after a current comment/reaction, remove the watch.
- Full scans compare currently parked issues with stored watches to repair missing watches and remove stale ones.
- Loop-breaker parks are not approval watches.
- Queue failures in watch maintenance degrade to the next full scan and never rewrite the run outcome.

**TDD and implementation steps:**

- [x] Add failing scan truth-table tests for never-scanned, hard maximum age with dirty work, immediately eligible dirty work, quiet-period suppression, normal interval, and overlapping scan leases.
- [x] Run uv run pytest -q tests/events/test_scan_policy.py and confirm failure. Initial RED: collection failed because `agent_sessions.events.driver` did not exist.
- [x] Implement ScanPolicy, RepositoryScanState, and scan_decision. Focused truth table: 6 passed.
- [x] Add failing LiveTargetResolver tests for issue, PR closing references, revision-to-current-PR resolution, convergence of several target shapes on one issue, missing objects, and control-plane targets. Added current thread, reaction, and board-state cases as well.
- [x] Add failing QueueSelection tests for irrelevant acknowledgement, housekeeping acknowledgement, transient retry/backoff, lock-contention release, bounded batch, priority ordering, at-most-one invocation, and non-selected release. A multi-closing-issue regression also caught and fixed release of the selected claim.
- [x] Run uv run pytest -q tests/events/test_driver.py and confirm failure. Initial RED was the missing `QueueRuntime`; focused live-state RED later showed three expected failures, and the multi-closing-issue RED exposed the selected-lease bug.
- [x] Implement github.py and driver.py with no transaction spanning a resolver call. The final focused events suite passed 16 driver tests plus 6 scan-policy tests.
- [x] Add a failing lifecycle test proving after_inflight sees a durable marker and is called before any backend/deterministic phase. Initial focused lifecycle RED had 8 failures for the absent config/callback seams.
- [x] Add a failing regression proving main without events configuration performs the current full scan and makes no queue import/open call.
- [x] Add failing degraded-mode cases for absent database, locked database beyond busy timeout, corrupt database, and incompatible schema; assert each uses the legacy full scan.
- [x] Implement the minimal lifecycle wiring and approval-watch hooks. The focused lifecycle/full-loop regression set passed, including callback-error fallback and watch repair.
- [x] Add an integration test that posts a signed PR delivery through ASGI, claims it, resolves current GitHub fixture state, selects the existing phase, writes inflight, and conditionally acknowledges the claim. The test also proves a concurrent generation survives.
- [x] Run make events-test. Final run exited 0.
- [x] Run make driver-test. Final run exited 0 with the existing two skips.
- [x] Run make lint. Final output: `All checks passed!`
- [x] Run make typecheck. Final output: `Success: no issues found in 98 source files`.
- [x] Run make check. Final run exited 0; the existing gate-test availability check remained explicitly skipped.
- [x] Commit only Phase 3 files with message: Phase 3: reconcile queue hints before full scans

### Review fix round 1

- [x] Restrict permanent claim disposition to authoritative absence. HTTP 401/500, transport failures, a missing `gh` executable, malformed/incomplete pagination, and board-read failures now retry; confirmed object 404s remain acknowledgeable.
- [x] Distinguish a complete full issue snapshot from legacy empty selection. An incomplete snapshot finishes the repository lease as failed, preserves the last-success clock and watches, and does not repair from partial data.
- [x] Release any selected Git-ref lock before every queue-error fallback. Regressions cover post-lock non-selected release and scan-completion failures and observe one legacy fallback with no stranded ref.
- [x] Move attempt advancement after successful selected-claim acknowledgement. An acknowledgement failure at attempt 2 falls back and invokes once at attempt 3 instead of triggering the loop breaker before a backend starts.
- [x] Remove approval watches only after a fresh label read confirms unpark. Failed targeted and full-scan label removal retain the watch; verification failures remain outcome-isolated.
- [x] Timestamp new watches from the persisted park transition after classification, not invocation start. The distinct-clock regression observes `12:10` for a run begun at `12:00`.
- [x] Route explicit `--issue` and `--retry` through a leased full snapshot before dirty claims. Both work without a matching claim, and an unrelated dirty generation remains untouched.
- [x] Paginate review threads, parked issue comments/reactions, open-PR discovery, and nested closing references. Multi-page regressions prove later unresolved threads, reactions, and PRs affect current routing inputs.
- [x] Review-fix verification: focused events/scan and driver/full-loop suites passed; `make events-test`, `make driver-test`, `make lint`, `make typecheck`, `make check`, and `git diff --check` exited 0. `make check`: 743 passed, 2 skipped.

### Review fix round 2

- [x] Treat a successful 500-row issue-list response as ambiguous rather than complete. The 499-row boundary advances the scan clock and repairs stale watches; the 500-row boundary finishes failed, preserves prior success/watch state, starts no agent, and releases the candidate Git lock.
- [x] Require a well-formed authoritative labels list before confirming unpark. Missing/null/mapping/string labels and malformed list entries preserve approval watches in targeted and full-scan paths; failures remain isolated from routing outcomes.
- [x] Replace direct `gh pr view` closing associations with the complete GraphQL closing-reference connection. Direct PR and revision claims include later-page issues; missing pageInfo and page-fetch failure retry without acknowledgement.
- [x] Round-two TDD: scan-cap RED was 1 pass/1 failure and GREEN was 4 passes with adjacent scan cases; each malformed-label table produced 5 failures/1 existing pass and then targeted/full GREEN totals of 8 and 7; direct-PR pagination produced 4 failures then 4 passes.
- [x] Round-two verification: focused events/scan and driver/full-loop suites exited 0; `make events-test`, `make driver-test`, `make lint`, `make typecheck`, `make check`, and `git diff --check` exited 0. `make check`: 751 passed, 2 skipped.

**Verification — automated:**

- [x] A driver without events configuration follows the legacy full-scan call path. The regression counts one call and makes queue loading fail the test if reached.
- [x] An unavailable/incompatible configured database logs degraded mode and follows the same legacy path. Absent, locked, corrupt, and ahead-schema databases each emit exactly one degraded event.
- [x] PR and revision targets resolve current closing issues rather than trusting payload associations.
- [x] At most one agent session starts, and selected acknowledgement occurs after inflight durability. Direct execute/request-review ordering and main-loop callback-error fallback are covered.
- [x] A concurrent generation survives selected-target acknowledgement. The signed ASGI integration leaves generation 2 dirty and unleased.
- [x] Full scans obey hard deadline, quiet period, interval, and repository scan lease rules.
- [x] Existing make driver-test routing and recovery behavior passes.
- [x] make lint, make typecheck, and make check pass.

**Verification — manual:**

- [x] Review the lifecycle diff for changes outside the optional selection wrapper, inflight callback, and approval-watch hooks. No adjacent legacy selection logic was refactored.
- [x] Confirm every router/reconciler decision is fed freshly fetched GitHub state. Issue/PR associations, labels, comments/reactions, board state, threads, CI, reviews, and merge state all come from targeted reads; queue payloads contribute identity only.
- [x] Confirm the existing Git-ref lock remains the last exclusion check before a candidate is returned.

---

## Task 4: Phase 4 — Projects and approval-reaction pollers

This phase fills the two webhook gaps with separate one-shot commands. Projects polling establishes a complete silent baseline and then atomically snapshots membership/Status/Priority changes; reaction polling queries only active approval watches and emits only when the predicate changes.

**Files:**

- Create: src/agent_sessions/events/pollers.py — pure diffing plus one-pass orchestration.
- Create: tests/events/test_poll_projects.py
- Create: tests/events/test_poll_reactions.py
- Modify: src/agent_sessions/events/github.py — paginated board projection and watched-approval reads.
- Modify: src/agent_sessions/events/cli.py — add poll-projects and poll-reactions.
- Modify: src/agent_sessions/driver/credentials.py — add scoped read-token and board-token resolvers that do not load the write token.
- Modify: tests/driver/test_credentials.py — prove scoped resolution never executes or returns broader credential commands.

**Scoped credential interface:**

    def resolve_read_credential(
        env: Mapping[str, str] | None = None,
        *,
        runner: CommandRunner | None = None,
        http_post: Callable[..., str] | None = None,
    ) -> str:
        ...

    def resolve_board_credential(
        env: Mapping[str, str] | None = None,
        *,
        runner: CommandRunner | None = None,
    ) -> str:
        ...

resolve_read_credential loads AGENT_GH_READ_TOKEN or its command, otherwise mints only the existing scoped installation read token. resolve_board_credential loads DRIVER_GH_BOARD_TOKEN or its command. Neither reads DRIVER_GH_WRITE_TOKEN or its command. Existing credentials.resolve behavior remains unchanged for the driver.

**Projects poller:**

github.fetch_project_items(board, token) uses GraphQL pageInfo.hasNextPage/endCursor and fetches every page outside a transaction. It returns CompleteProjectSnapshot only after all pages parse and every supported item has stable node ID, content type, repository ID/name, number, Status, and Priority. Rate-limit, transport, GraphQL error, malformed page, or missing terminal pageInfo raises PollFailure and supplies no partial snapshot.

    @dataclass(frozen=True)
    class CompleteProjectSnapshot:
        board_key: str
        items: tuple[ProjectItemProjection, ...]
        fetched_at: datetime

    class PollFailure(RuntimeError):
        pass

    def diff_project_snapshot(
        before: Iterable[ProjectItemProjection],
        after: Iterable[ProjectItemProjection],
    ) -> tuple[Invalidation, ...]:
        ...

The first complete fetch stores a baseline and emits none. poller_state.last_success_at, not the presence of project_items rows, distinguishes an established empty baseline from a board that has never been fetched. Later diffs emit only for added/removed membership or changed Status/Priority. Removal uses the stored prior repository/content coordinates. Other field changes are ignored. QueueStore.replace_project_snapshot commits the complete new snapshot and its synthetic invalidations atomically. Failed/incomplete fetches preserve the prior snapshot and mark poller failure.

poll-projects acquires source key projects:<owner>/<number>, exits successfully without work when another live lease owns it, performs one fetch, commits one snapshot, records poll success, logs counts, and exits. It holds no SQLite transaction during GraphQL pagination.

**Reaction poller:**

github.fetch_approval_predicates groups active watches by repository and queries only those issue numbers/comments/reactions, paginating until every watched issue is resolved. The predicate is true when a non-bot human comment or THUMBS_UP reaction exists after parked_at, matching the driver's current unpark semantics.

QueueStore.record_watch_observation performs the conditional watch update and matching synthetic issue invalidation in one transaction. It returns true exactly when a prior observed value exists and differs. A first observation establishes state silently. Concurrent pollers are excluded by source key reactions:<repository-id>.

poll-reactions acquires one source lease per repository, fetches outside a transaction, conditionally updates observations and invalidations in one transaction, records success, and exits after one pass. Failure leaves last_value and last_checked_at unchanged and exits nonzero.

**TDD and implementation steps:**

- [x] Add failing credential tests proving the Projects resolver never evaluates write/read token commands and the reaction resolver never evaluates write/board token commands. The focused RED produced five expected missing-resolver failures; guarded mappings fail on any broader-key access.
- [x] Implement scoped credential resolution by reusing existing token-command and App-token helpers. `tests/driver/test_credentials.py` passed after GREEN; absence-path guards also forbid broader literal fallback.
- [x] Add failing pure project-diff tests for silent baseline, add, remove with old coordinates, Status change, Priority change, irrelevant-field change, and cross-repository filtering. Literal expected invalidations cover each permitted change.
- [x] Add failing paginated fetch tests for complete multi-page results, GraphQL/rate-limit failure, malformed middle page, and missing pageInfo; assert no snapshot mutation on every failure. Complete response fixtures include item/content/field/rate-limit/pageInfo shapes.
- [x] Run uv run pytest -q tests/events/test_poll_projects.py and confirm failure. RED stopped at collection on the absent `CompleteProjectSnapshot` API.
- [x] Implement Projects fetch/diff/one-pass orchestration. The focused suite passed after GREEN and after the source-provenance regression.
- [x] Add failing reaction tests for first silent observation, false-to-true and true-to-false changes, unchanged predicates, human-vs-bot filtering, park timestamp boundary, grouped pagination, source lease exclusion, and failed-fetch preservation.
- [x] Run uv run pytest -q tests/events/test_poll_reactions.py and confirm failure. RED stopped at collection on the absent `fetch_approval_predicates` API.
- [x] Implement reaction fetch/conditional update/one-pass orchestration. The focused suite passed after GREEN, including re-park baseline reset.
- [x] Add an integration test that writes an approval watch, runs the synthetic reaction observation through QueueStore, and lets the driver claim the resulting issue target. `test_changed_reaction_observation_is_claimable_by_the_driver` exercises the real store.
- [x] Add poll-projects and poll-reactions CLI composition with no resident scheduler. CLI tests prove one invocation and the command-specific credential resolver.
- [x] Run make events-test. All 180 event tests passed.
- [x] Run make driver-test. 758 passed and 2 skipped.
- [x] Run make lint. Ruff and the repository lint checks passed.
- [x] Run make typecheck. Mypy reported no issues in 101 source files.
- [x] Run make check. The complete target exited 0 with 758 passed, 2 skipped, and the documented gate-test availability skip.
- [x] Commit only Phase 4 files with message: Phase 4: add project and reaction pollers. Named-path staging excludes the ignored task brief/report and every file outside this phase.

**Verification — automated:**

- [x] The first complete Projects fetch is silent and every later membership/Status/Priority difference emits exactly one coalesced target generation. Covered by `test_first_complete_project_fetch_is_a_silent_baseline_even_when_empty` and literal diff cases.
- [x] Incomplete Projects fetches preserve the old snapshot and cannot infer removals. Covered for transport, GraphQL, rate-limit, malformed-middle-page, and missing-pageInfo failures.
- [x] Approval predicates emit only on conditional value changes and concurrent pollers cannot duplicate a pass. Covered by the observation sequence and source-lease tests.
- [x] The synthetic-poll-to-SQLite-to-driver-claim integration test passes. The claimed coordinates are `(1, issue, 42)`.
- [x] Scoped credential tests prove each poller cannot receive the write credential. Forbidden-key mappings cover literal, command, App-mint, and absence paths.
- [x] make lint, make typecheck, make driver-test, and make check pass. The focused credential/project/reaction suite also passed all 92 tests.

**Verification — manual:**

- [x] Review the GraphQL loops for explicit pageInfo handling and no record-count shortcut. Every connection page is validated; terminal `hasNextPage` must be false.
- [x] Confirm source-specific leases distinguish every configured board and repository. Keys are `projects:<owner>/<number>` and `reactions:<repository-id>` in leases and synthetic provenance.
- [x] Confirm each command performs one pass and contains no internal timer or scheduler. CLI composition invokes one `poll_*_once` function and returns its exit code.

### Review fix round 1

- [x] Sanitize scoped credential failures without changing the broad driver resolver. Four adversarial resolver/CLI cases first exposed child stderr and App exception content; traceback-chain and empty-App regressions then exposed two remaining metadata leaks. Scoped errors now report only variable, failure category, exception type where safe, and exit status; eight category/leak cases pass.
- [x] Make approval observation writes a full compare-and-swap. Two real-store interleavings first reproduced stale reverse invalidation and timestamp regression; the SQL predicate now includes fetched `parked_at`, `last_value`, and `last_checked_at`, and both cases pass without extra invalidations.
- [x] Apply the current board repository allowlist before project diffing. The regression first emitted two removals; it now emits only the still-configured repository removal while silently dropping the stale unconfigured row.
- [x] Reject malformed Projects item discriminators and page cursors while retaining known unsupported items. Seven malformed fixtures first committed destructive diffs; all now fail closed, while complete DraftIssue and null-content REDACTED shapes remain ignorable.
- [x] Fence post-fetch writes on lease owner and unexpired lease inside each SQLite transaction. Projects and reactions each first mutated after a real second-store lease handoff; bare-expiry mutation checks also failed when the expiry predicate was removed, and a two-watch batch exposed reuse of one pre-expiry clock value. All five owner/expiry regressions now return nonzero without stale mutation.
- [x] Re-run the focused suites, `make events-test`, `make driver-test`, `make lint`, `make typecheck`, `make docs-check`, `make check`, and `git diff --check`; inspect named staging and amend the Phase 4 commit. The focused suite passed 118 cases, events passed 199, driver/full check passed 765 with 2 skipped, and all static/docs/diff checks exited 0.

---

## Task 5: Phase 5 — Operational diagnostics, service examples, and runbook

This phase makes the system deploy-ready without deploying it. doctor validates configuration, SQLite, identities, board/read capabilities, and file permissions; examples show one-worker receiver and one-shot timers; the runbook documents migration, readiness, recovery, and credential isolation.

**Files:**

- Create: docs/events.md — operator runbook.
- Create: examples/agent-session-events/events.toml — non-secret annotated configuration.
- Create: examples/agent-session-events/agent-session-events-webhook.service
- Create: examples/agent-session-events/agent-session-projects.service
- Create: examples/agent-session-events/agent-session-projects.timer
- Create: examples/agent-session-events/agent-session-reactions@.service
- Create: examples/agent-session-events/agent-session-reactions@.timer
- Create: examples/agent-session-events/agent-session-driver@.service
- Create: examples/agent-session-events/Caddyfile — webhook-only reverse proxy example; health routes remain loopback.
- Create: tests/events/test_examples.py — structural checks over examples.
- Modify: src/agent_sessions/events/operations.py — complete live doctor and richer status diagnostics.
- Modify: src/agent_sessions/events/cli.py — final command help/exit behavior.
- Modify: README.md — short pointer to docs/events.md, not duplicated operational state.
- Modify: docs/usage.md — cross-reference the optional queue-first mode and legacy fallback.
- Modify: Makefile — document events-test and example validation in help if not already present.

**Doctor contract:**

doctor is read-only with respect to GitHub and reports each probe as pass, fail, warn, or skip:

- TOML parse and all strict configuration invariants.
- Database parent/file ownership and restrictive modes.
- SQLite open, integrity_check, foreign_key_check, WAL mode, busy timeout, and exact schema compatibility.
- Configured repository numeric IDs and owner/name against GET /repos/{owner}/{name}.
- Installation read credential can read each configured repository using resolve_read_credential.
- Board credential can read every configured board and its Status/Priority fields using resolve_board_credential.
- Webhook secret file exists, is owner-only, and is non-empty, without printing it.
- queue-status clocks/leases are readable; no latest success is rendered as a pass when none exists.

doctor does not probe by writing a label or project item. Capability it cannot prove with a read becomes skip or warn with a precise remedy.

**Service and proxy invariants:**

- Webhook ExecStart uses agent-session-events serve --config <path> with one Uvicorn worker.
- Projects and reaction units are Type=oneshot; timers own cadence.
- Each unit loads only its scoped EnvironmentFile or service credential.
- The driver timer passes --events-config while preserving existing repo/workspace/model configuration elsewhere.
- migrate is documented as an explicit stopped-services step and relies on its exclusive SQLite transaction.
- Caddy routes only /github/webhook to the receiver; /healthz and /readyz are not public.
- No example contains a token, webhook secret, private key, real repository ID, or executable deployment command.

**Runbook sections:**

- Configuration and directory/file permissions.
- GitHub App event subscription and read permissions, with Projects using the separate board credential and no Actions permission.
- Fresh install: stop units, run migrate, run doctor, inspect queue-status, start units manually.
- Upgrade: stop units, back up the local database/WAL files, run migrate, run doctor, restart manually.
- Readiness and degraded driver behavior.
- Timer responsibilities and expected one-pass exit codes.
- queue-status human/JSON examples, lease/backoff interpretation, and recent errors.
- Safe pruning and WAL checkpoint behavior.
- Recovery for unavailable, busy, incompatible, and corrupt databases; no automatic repair.
- Explicit statement that full scans remain authoritative and dirty rows are not age-pruned or bulk-cleared.
- Explicit non-deployment boundary: commands are examples for Les to review and run.

**TDD and implementation steps:**

- [x] Add failing doctor tests for each probe/status above, including repository-ID mismatch, inaccessible board, incompatible schema, absent success clocks, and secret-file modes without secret disclosure. The first focused RED produced 14 expected failures and 12 passes; the CLI error-path RED then produced 2 expected failures and 26 passes.
- [x] Complete doctor and queue-status diagnostics. `uv run pytest -q tests/events/test_operations.py` passed all 28 cases.
- [x] Add failing structural example tests for one worker, one-shot pollers, timer ownership, scoped EnvironmentFile use, webhook-only proxying, no secret literals, and no deployment invocation. The focused RED produced 8 expected failures: seven absent example artifacts and the absent one-worker argument.
- [x] Add the example files and run uv run pytest -q tests/events/test_examples.py. All 7 structural cases passed; the combined service/worker regression passed 8 cases.
- [x] Write docs/events.md and add only short cross-references to README.md and docs/usage.md. The runbook keeps deployment commands abstract and identifies prerequisites and expected outcomes.
- [x] Run agent-session-events --help and each subcommand --help; record command names and exit codes. Top-level, serve, poll-projects, poll-reactions, doctor, queue-status, migrate, and prune help each exited 0.
- [x] Run make events-test. All 227 collected event tests passed.
- [x] Run make driver-test. 765 passed and 2 skipped.
- [x] Run make lint. Ruff reported all checks passed.
- [x] Run make typecheck. Mypy reported no issues in 102 source files.
- [x] Run make docs-check. It exited 0; links, tables, counts, and risk policies passed, while its nested gate-test assertion-count probe remained explicitly skipped rather than reported as verified.
- [x] Run make check. The complete target exited 0 with 765 passed, 2 skipped, and the documented nested assertion-count skip.
- [x] Commit only Phase 5 files with message: Phase 5: document event queue operations. Named-path staging contained the 19 Phase 5 files and excluded the ignored task brief/report.

**Verification — automated:**

- [x] doctor distinguishes failure, warning, skip, and pass without making GitHub writes. Exact command-vector assertions allow only repository GET and project field-list reads; adversarial stderr and credential contents remain absent from output.
- [x] Example structure tests enforce one worker, one-shot pollers, timer cadence ownership, credential separation, and private health routes. TOML, systemd units, commands, and Caddy blocks are parsed before their semantics are asserted.
- [x] agent-session-events exposes serve, poll-projects, poll-reactions, doctor, queue-status, migrate, and prune; repair-deliveries is absent. Behavioral help checks and all eight installed help invocations exited 0.
- [x] make events-test, make driver-test, make docs-check, and make check pass. Events passed 227; driver and complete checks passed 765 with 2 skipped; docs-check exited 0 with its explicit nested assertion-count skip.

**Verification — manual:**

- [x] Review docs/events.md as a cold operator and verify every command names prerequisites and expected outcome.
- [x] Review examples for placeholders that cannot accidentally point at a real service or repository.
- [x] Confirm no deployment, GitHub App mutation, Caddy reload, systemctl action, or infrastructure write was performed.
- [x] Confirm dependency, shipping src, lifecycle, and credential changes remain needs-review regardless of test results.

### Review fix round 1

- [x] Make the systemd topology executable under owner-only database permissions. All SQLite clients share one Unix identity, and parsed unit tests require the driver command and `ReadWritePaths` to name its repository, state, workspace, and database paths.
- [x] Normalize wrong top-level TOML types and malformed stored clocks at diagnostic boundaries. Focused tests cover non-string database values, non-array repositories and boards, clean CLI exits, non-disclosure, and continued independent probes.
- [x] Validate schema shape without mutation. Damage tests remove `project_items`, `invalidations`, and a required index; each reports `sqlite-schema=fail` while the captured `sqlite_master` rows remain unchanged.
- [x] Make board field diagnosis complete before testing field absence. The exact command vector includes `--limit 1000`, and a `totalCount` mismatch produces a skip rather than a false missing-field failure.
- [x] Document exact credential variables and command-backed forms, bot metadata, service EUID and modes, separated-environment doctor runs, and the all-configured-repositories scope of reaction instances. Replace the hard-coded schema number in the output example.
- [x] Assert the exact top-level CLI command set. The focused review RED produced 13 expected failures among 60 cases; GREEN passed all 60, and the operations/example subset passed 44.
- [x] Re-run all required verification. All eight help surfaces exited 0; `make events-test` passed 239 collected tests; `make lint`, `make typecheck`, and `make docs-check` exited 0; and `make check` passed 765 tests with 2 skips. Both worktree and staged diff checks pass.

### Review fix round 2

- [x] Restore the receiver-only-secret boundary with four distinct Unix service identities. Parsed unit tests require private primary groups, the common `agent-session-events-db` supplementary group, `UMask=0007`, the shared database write path, and the driver's explicit repository/state/workspace paths.
- [x] Define group sharing as executable data. The parsed permission manifest requires a setgid `2770` database directory and `0660` database while proving each credential file is `0600`, belongs to its service's private group, and is not readable by `agent-session-events-db`.
- [x] Preserve database group access across migration and diagnosis. A focused real-filesystem test proves migration selects `0660` only for the reviewed shared-directory shape; doctor tests prove a group member passes, a non-member fails, and world access still fails. The webhook-secret test retains strict EUID/owner-only behavior.
- [x] Document exact account, group, ownership, mode, migration EUID/umask, WAL/SHM, and separately scoped doctor requirements for a cold operator. No brittle prose-content assertion was added.
- [x] Record RED and GREEN. The five-case RED produced four expected failures and one pass; the unchanged GREEN command passed five in 1.88 seconds. The complete store/operations/example focus passed 65, and operations/examples passed 47.
- [x] Re-run required verification. `make events-test` passed 243 cases; lint, typecheck, and docs-check exited 0; `make check` passed 765 tests with 2 skips; and worktree/staged diff checks passed.

### Whole-branch review fix

- [x] Expand exact App read permissions and probe check-run and combined-status access with pass, fail, and empty-repository skip behavior.
- [x] Normalize repository-less control-plane deliveries before repository-scoped validation and constrain all targets to configured installation and repository identities.
- [x] Materialize every unselected actionable issue from a selected PR claim before conditional source acknowledgement; preserve coalescing and stale-generation safety.
- [x] Require set-group-ID for shared database directories, validate existing SQLite sidecars, and keep diagnosis from creating source sidecars.
- [x] Derive complete required table and index metadata from shipped migrations; reject type, nullability, default, primary-key, and uniqueness damage.
- [x] Reject non-positive retention overrides before pruning and persist failed full-scan errors through the new ordered migration.
- [x] Record behavioral RED and GREEN evidence. The combined focused GREEN command passed 88 cases after every finding failed for its stated reason.
- [x] Complete the final broad verification. `make events-test` passed 265 cases; `make driver-test` and `make check` passed 765 with 2 skips; lint, typecheck, docs-check, and all eight CLI help surfaces exited 0. Inspect the whole branch, amend Phase 5, and record the new commit in the final fix report.

### Whole-branch scoped re-review

- [x] Reproduce source-sidecar mutation with a valid WAL-only source and an existing-SHM source. RED failed both cases for the reviewed reasons: source SHM creation and source SHM byte/time mutation.
- [x] Copy the database and existing WAL/SHM files to matching basenames in a private temporary directory before any SQLite open. Preserve source path and permission probes; open only the copied set.
- [x] Verify source immutability and cleanup. The two new cases and the existing both-absent guard passed; the complete operations/store focus passed 76 cases.
- [x] Re-run the required gates. `make events-test` passed 267 cases; lint, typecheck, and docs-check exited 0; and `make check` passed 765 tests with 2 skips.

---

## Final acceptance and PR preparation

- [x] Run make events-test and record the exact result. Final controller run exited 0 with 267 passing tests.
- [x] Run make driver-test and record the exact result. Final controller run exited 0 with 765 passed and 2 documented skips.
- [x] Run make check and record the exact result. Final controller run exited 0 with 765 passed, 2 documented skips, and `all checks passed`.
- [x] Run git diff --check and inspect git diff origin/main...HEAD. The final diff check is clean; the inspected range contains only the 54 planned source, test, dependency, example, runbook, and dev-session files.
- [x] Verify every acceptance bullet in spec.md maps to a named test above. Webhook behavior maps to `test_webhook.py`; queue races and migrations to `test_store.py`; mappings to `test_normalize.py`; queue-first/degraded selection to `test_driver.py`, `test_scan_policy.py`, and `test_full_loop.py`; Projects and reactions to their named poller suites; executable operations/examples to `test_operations.py` and `test_examples.py`.
- [x] Confirm the branch contains five logical Phase commits and no deployment action. Final history has exactly the five required Phase subjects; reports and reviews confirm no service-manager, proxy, GitHub, push, PR, or infrastructure mutation.
- [x] Use the dev-session PR workflow; request and address Copilot review, but do not merge. PR #275 opened with five Phase commits. Copilot's uppercase-signature finding reproduced as a 401, then passed after case normalization; the empty-research-artifact note was clarified. No merge occurred.

## Coverage map and self-review

- SQLite schema, migrations, QueueStore, generations, claims, leases, inspection, forward migration, and pruning: Phase 1.
- Exact-byte HMAC, streaming limits, HTTP status behavior, deduplication, readiness, docs-route disabling, selected event mappings, and signed ASGI integration: Phase 2.
- Live PR/revision resolution, queue-first driver behavior, inflight acknowledgement, scan policy, issue locks, watch repair, legacy fallback, and database degradation: Phase 3.
- Complete Projects pagination/baselines/diffs, approval predicate changes, source leases, scoped credentials, and synthetic-poll integration: Phase 4.
- Full doctor behavior, structured operational guidance, service/proxy examples, command surface, and non-deployment boundary: Phase 5.
- Unknown events/actions and unconfigured repositories are retained as verified diagnostic deliveries but produce no dirty targets.
- Every non-trivial interface used by a later phase is defined in an earlier phase or in Shared file structure and interfaces.
- No phase changes gate.py, router policy, write-manifest kinds, automatic merge behavior, or deployment state.
- No unresolved design question or placeholder remains. Manual review boxes stay unchecked until Les reviews the corresponding artifact.

---

## Review revision — combined event daemon and system-wide reads

The owner review on PR #275 supersedes the service topology completed in Tasks 4 and 5. The immutable queue, webhook behavior, one-pass pollers, and queue-first driver remain valid. Tasks 6–8 replace only the process scheduling, read-credential wiring, fragile GraphQL test dispatch, review nits, service examples, and affected documentation. Checked boxes above remain historical evidence; unchecked boxes below are the current resume point.

## Task 6: Combined event daemon and shared read credential

This slice makes `serve` the complete read-only event process. It starts the existing one-pass pollers on in-process fixed-delay loops, gives every event read the same credential already used by the driver and agent, and keeps webhook work independent from polling failures.

**Files:**

- Create: `src/agent_sessions/events/daemon.py` — background poll-loop lifecycle and readiness.
- Create: `tests/events/test_daemon.py` — deterministic runtime scheduling, failure, connection, and shutdown tests.
- Modify: `src/agent_sessions/events/models.py` — add polling configuration.
- Modify: `src/agent_sessions/events/config.py` — parse the strict `[polling]` table.
- Modify: `src/agent_sessions/events/store.py` — add an explicit connection close boundary.
- Modify: `src/agent_sessions/events/webhook.py` — attach the daemon lifespan and include task health in readiness.
- Modify: `src/agent_sessions/events/cli.py` — resolve one read credential and build both scheduled poll passes.
- Modify: `src/agent_sessions/events/operations.py` — probe repositories and Projects with the same read token.
- Modify: `src/agent_sessions/driver/credentials.py` — make the event-facing read resolver accept only the literal or command-backed PAT while preserving `resolve()` App minting for the driver.
- Modify: `src/agent_sessions/events/github.py` — bound each `gh` read used by an in-flight poll pass.
- Test: `tests/events/test_config.py`
- Test: `tests/events/test_webhook.py`
- Test: `tests/events/test_operations.py`
- Test: `tests/events/test_poll_projects.py`
- Test: `tests/events/test_poll_reactions.py`
- Test: `tests/driver/test_credentials.py`

**Interfaces:**

- Produces `PollingPolicy(projects_interval: timedelta, reactions_interval: timedelta)` and `EventsConfig.polling: PollingPolicy`.
- Produces `ScheduledPoll(name: str, interval: timedelta, run: PollPass)` where `PollPass = Callable[[QueueStore, datetime], PollRunResult]`.
- Produces `DaemonRuntime(store_factory: Callable[[], QueueStore], polls: tuple[ScheduledPoll, ...], result_logger: Callable[[str, PollRunResult], None])` with `lifespan(app)`, `ready() -> bool`, and no public scheduling methods.
- Produces `QueueStore.close() -> None` for the per-pass connection boundary.
- Changes `create_app(..., runtime: BackgroundRuntime | None = None) -> FastAPI`; tests that exercise the receiver alone may omit the runtime.
- Keeps `credentials.resolve()` unchanged for driver-side PAT or App resolution. `resolve_read_credential()` resolves only `AGENT_GH_READ_TOKEN` or `AGENT_GH_READ_TOKEN_CMD` and never inspects App or board-write variables.

```python
@dataclass(frozen=True)
class ScheduledPoll:
    name: str
    interval: timedelta
    run: PollPass


class DaemonRuntime:
    async def _run(self, poll: ScheduledPoll) -> None:
        while not self._stopping.is_set():
            store = self._store_factory()
            try:
                result = await asyncio.to_thread(poll.run, store, datetime.now(UTC))
                self._result_logger(poll.name, result)
            finally:
                store.close()
            try:
                await asyncio.wait_for(
                    self._stopping.wait(), poll.interval.total_seconds()
                )
            except TimeoutError:
                pass
```

Expected source failures remain values in `PollRunResult.errors`, so the loop logs them and continues. An exception escaping a scheduled pass ends only that task; `ready()` then returns false. Lifespan shutdown sets the stopping event and gathers every task. `GitHubResolver._read` passes `timeout=60` to `subprocess.run` and translates `subprocess.TimeoutExpired` into `GitHubTransientError`, which bounds an in-flight poll during shutdown.

The CLI omits the Projects task when `config.boards` is empty. The reaction task always starts; with no active watches its one-pass function performs no GitHub request. Both scheduled closures receive the single startup-resolved read PAT, open a new store per pass through `DaemonRuntime`, and retain the existing source leases.

**TDD and implementation steps:**

- [x] Add failing configuration tests proving `[polling]` is required, both interval keys are required positive integers, and unknown polling keys fail closed.
- [x] Run `uv run pytest -q tests/events/test_config.py` and confirm the new cases fail because `PollingPolicy` and `[polling]` parsing do not exist.
- [x] Add `PollingPolicy`, parse the strict table, and update existing configuration fixtures with explicit 60-second values.
- [x] Run `uv run pytest -q tests/events/test_config.py` and confirm the configuration suite passes.
- [x] Add failing daemon tests proving both loops run immediately, wait their own fixed interval after completion, never overlap themselves, open and close a distinct real `QueueStore` per pass, continue after a `PollRunResult` with errors, report an escaped exception through `ready()`, omit Projects when no boards exist, and finish an in-flight bounded pass during lifespan shutdown.
- [x] Run `uv run pytest -q tests/events/test_daemon.py tests/events/test_webhook.py` and confirm failures identify the missing runtime and readiness integration.
- [x] Implement `QueueStore.close`, `ScheduledPoll`, `DaemonRuntime`, and the optional webhook runtime protocol. Keep every GitHub call outside the webhook request task and every poll pass outside the receiver's SQLite connection.
- [x] Add the 60-second subprocess timeout and its focused timeout-to-transient-error regression.
- [x] Run `uv run pytest -q tests/events/test_daemon.py tests/events/test_webhook.py` and confirm the runtime and receiver cases pass.
- [x] Add failing credential/CLI/doctor tests proving `serve`, both one-shot pollers, repository probes, and Project probes use one resolved read token; prove guarded environments fail if event code inspects `DRIVER_GH_WRITE_TOKEN`, `DRIVER_GH_BOARD_TOKEN`, or any App private-key variable.
- [x] Run `uv run pytest -q tests/driver/test_credentials.py tests/events/test_poll_projects.py tests/events/test_poll_reactions.py tests/events/test_operations.py` and confirm the new assertions fail on the board resolver and direct App-mint path.
- [x] Narrow `resolve_read_credential`, wire the shared token through `serve` and both one-shot commands, and replace doctor's board resolver with the already-resolved read token. Preserve `resolve()` and `board_env()` for driver writes.
- [x] Run the focused credential, CLI, doctor, daemon, and webhook suites and confirm they pass.
- [x] Run `make events-test`, `make driver-test`, `make lint`, and `make typecheck`.
- [x] Commit the named Task 6 files with message `Review: combine event polling with webhook service`.

**Verification — automated:**

- [x] `uv run pytest -q tests/events/test_daemon.py tests/events/test_webhook.py` passes.
- [x] `uv run pytest -q tests/driver/test_credentials.py tests/events/test_poll_projects.py tests/events/test_poll_reactions.py tests/events/test_operations.py` passes.
- [x] `make events-test`, `make driver-test`, `make lint`, and `make typecheck` pass.

**Verification — manual:**

- [x] Confirm the event daemon receives no repository-write or Project-write credential.
- [x] Confirm no background GitHub work runs in the webhook handler or shares its SQLite connection.
- [x] Confirm normal poll failures remain visible in `queue-status` without making webhook ingress unready.

## Task 7: Explicit GraphQL operations and review clarity fixes

This slice addresses the three focused code-quality comments without broadening into unrelated driver refactors: new event GraphQL queries gain stable identities, transaction rollback follows one path, and the supported non-queue path gets an accurate name.

**Files:**

- Modify: `src/agent_sessions/events/github.py` — typed named GraphQL documents.
- Modify: `tests/driver/loop_harness.py` — exact operation parsing and dispatch for event queries.
- Modify: `tests/events/test_driver.py` — operation-name regression through the strong fake if needed by the existing integration fixture.
- Modify: `src/agent_sessions/events/store.py` — one transaction exception path and quiet rollback helper.
- Modify: `tests/events/test_store.py` — begin, body, commit, rollback, translation, and application-exception regressions.
- Modify: `src/agent_sessions/driver/lifecycle.py` — replace “legacy mode” with “full-scan mode.”
- Modify: `tests/driver/test_full_loop.py` — use the same supported-mode name in test diagnostics.

**Interfaces:**

- Produces `GraphQLOperation(StrEnum)` with `UNRESOLVED_THREADS`, `ISSUE_REACTIONS`, `COMMENT_REACTIONS`, `OPEN_PULL_REQUEST_DISCOVERY`, `CLOSING_ISSUES`, and `PROJECT_ITEMS` members.
- Produces `GraphQLQuery(operation: GraphQLOperation, document: str)`; `_graphql_pages` accepts this type rather than a bare string.
- Every document begins with the corresponding GraphQL operation name, for example `query OpenPullRequestDiscovery(...)`.
- The strong fake extracts the operation with one anchored parser and converts it to `GraphQLOperation`; missing and unknown names remain unhandled test failures.

```python
class GraphQLOperation(StrEnum):
    OPEN_PULL_REQUEST_DISCOVERY = "OpenPullRequestDiscovery"
    CLOSING_ISSUES = "ClosingIssues"
    UNRESOLVED_THREADS = "UnresolvedThreads"
    ISSUE_REACTIONS = "IssueReactions"
    COMMENT_REACTIONS = "CommentReactions"
    PROJECT_ITEMS = "ProjectItems"


@dataclass(frozen=True)
class GraphQLQuery:
    operation: GraphQLOperation
    document: str
```

The transaction context uses `_rollback_quietly()` and one outer exception boundary. SQLite exceptions still pass through `_raise_queue_error`; non-SQLite exceptions roll back and propagate unchanged. A commit failure rolls back. A rollback failure never masks the original failure.

**TDD and implementation steps:**

- [x] Add failing tests requiring every event query to carry the exact named operation and requiring the strong fake to reject an unknown or anonymous event operation instead of matching a field substring.
- [x] Run the focused event-driver integration tests and confirm the anonymous query documents fail.
- [x] Add `GraphQLOperation`, `GraphQLQuery`, named documents, and exact enum dispatch in `loop_harness.py`. Retain pre-existing historical driver-query handling outside this PR's event operations.
- [x] Run the focused GraphQL resolver and full-loop tests and confirm they pass.
- [x] Add or tighten transaction tests so begin failure, statement failure, application exception, commit failure, and rollback failure each assert the original exception or translated queue exception.
- [x] Run `uv run pytest -q tests/events/test_store.py` before refactoring and record the current behavior as the green characterization baseline.
- [x] Replace the nested transaction exception blocks with `_rollback_quietly()` and one guarded path; this is a behavior-preserving refactor, so no artificial red test is required.
- [x] Run `uv run pytest -q tests/events/test_store.py` and confirm every characterization remains green.
- [x] Replace “legacy mode” with “full-scan mode” in the lifecycle docstring and affected test diagnostic.
- [x] Run the focused GraphQL, store, and full-scan tests.
- [x] Run `make events-test`, `make driver-test`, `make lint`, and `make typecheck`.
- [x] Commit the named Task 7 files with message `Review: make event operations explicit`.

**Verification — automated:**

- [x] No event query dispatch in `tests/driver/loop_harness.py` searches for connection-field substrings.
- [x] Transaction exception translation and rollback tests pass.
- [x] `make events-test`, `make driver-test`, `make lint`, and `make typecheck` pass.

**Verification — manual:**

- [x] Confirm the typed operation list covers only GraphQL documents introduced by this issue.
- [x] Confirm the transaction refactor does not convert `sqlite3.IntegrityError` into `QueueUnavailable`.
- [x] Confirm “full-scan mode” describes a supported configuration rather than a deprecated compatibility path.

## Task 8: Two-service examples and general operator documentation

This slice makes the deploy-ready artifacts describe the approved topology: one read-only event daemon and separate write-capable repository drivers. It removes the obsolete poller units and rewrites the runbook for a general operator.

**Files:**

- Create: `examples/agent-session-events/agent-session-events.service` — combined event daemon.
- Delete: `examples/agent-session-events/agent-session-events-webhook.service`
- Delete: `examples/agent-session-events/agent-session-projects.service`
- Delete: `examples/agent-session-events/agent-session-projects.timer`
- Delete: `examples/agent-session-events/agent-session-reactions@.service`
- Delete: `examples/agent-session-events/agent-session-reactions@.timer`
- Modify: `examples/agent-session-events/agent-session-driver@.service` — load the shared read environment in addition to the private driver environment.
- Modify: `examples/agent-session-events/events.toml` — add the explicit polling intervals.
- Modify: `examples/agent-session-events/permissions.toml` — one event identity, one readers group, shared read environment, private webhook and driver-write files.
- Modify: `tests/events/test_examples.py` — structural assertions for the two-service boundary and absence of poller timers.
- Modify: `docs/events.md` — general setup, use, diagnosis, migration, and recovery guide.
- Modify: `docs/usage.md` — distinguish the system read credential from driver-only mutation credentials.
- Modify: `README.md` — retain only the short runbook link and accurate process summary.
- Modify: `docs/dev-sessions/2026-08-25-1037-event-driven-invalidation-queue/notes.md` — record the reviewed design change and verification evidence.

**Service contract:**

```ini
[Service]
User=agent-session-events
Group=agent-session-events
SupplementaryGroups=agent-session-events-db agent-session-readers
EnvironmentFile=/etc/agent-session/read.env
Environment=AGENT_SESSION_WEBHOOK_SECRET_FILE=/etc/agent-session-events/webhook.secret
ExecStart=/usr/local/bin/agent-session-events serve --config /etc/agent-session-events/events.toml
```

The driver unit joins the same readers and database groups, loads `/etc/agent-session/read.env` plus its private instance environment, and remains `Type=oneshot`. `/etc/agent-session/read.env` is owned by `root:agent-session-readers` with mode `0640`; it contains only `AGENT_GH_READ_TOKEN` or `AGENT_GH_READ_TOKEN_CMD`. The webhook secret remains `0600` under the event user. Each driver instance environment remains `0600` under the driver user and contains write/runtime values, never a second read token.

**TDD and implementation steps:**

- [x] Add structural assertions for exactly one event service, no event poller timers, one event identity, a shared readers group/file, private webhook and write files, one-worker Uvicorn startup, webhook-only Caddy routing, and the driver's separate one-shot timer boundary.
- [ ] Run `uv run pytest -q tests/events/test_examples.py` and confirm failures name the obsolete files and credential layout. Behavioral RED remains unproven: the command could not start because the sandbox denied access to the uv cache, which was not a test result.
- [x] Add the combined service, update the driver/configuration/permission examples, and delete the five obsolete event unit files.
- [x] Run `uv run pytest -q tests/events/test_examples.py` and confirm the parsed artifacts pass.
- [x] Rewrite `docs/events.md` around the two-service data flow and ordered setup sequence. Remove personal names, separate-poller deployment paths, direct App minting for the daemon, and claims that read credentials must remain isolated from each other.
- [x] Update `docs/usage.md` and `README.md` only where the old topology or credential purpose is stated.
- [x] Run the Simple English skill from `~/.claude/skills/simple-english` over the rewritten `docs/events.md`; apply its procedural rules without changing code, commands, identifiers, paths, or output samples.
- [x] Run the Simple English self-check and record its result in `notes.md`.
- [x] Run `make events-test`, `make driver-test`, `make docs-check`, `make lint`, `make typecheck`, and `make check`.
- [x] Inspect `git diff --check` and the complete `origin/main...HEAD` diff; confirm no deployment, GitHub App mutation, service-manager action, Caddy reload, merge, or infrastructure write occurred.
- [x] Commit the named Task 8 files with message `Review: simplify event service operations`.

**Verification — automated:**

- [x] `uv run pytest -q tests/events/test_examples.py` passes.
- [x] `make events-test`, `make driver-test`, `make docs-check`, `make lint`, `make typecheck`, and `make check` pass.
- [x] `git diff --check` passes.

**Verification — manual:**

- [x] Read `docs/events.md` cold and confirm the first page explains why two services remain.
- [x] Confirm every setup command states its prerequisite and expected outcome.
- [x] Confirm the examples contain placeholders only and cannot accidentally target a real repository or service.
- [x] Confirm no documentation names a specific operator as the required reviewer.

## Review-revision acceptance and PR response

- [x] Re-run `make events-test` and record the fresh result in `notes.md`.
- [x] Re-run `make driver-test` and record the fresh result in `notes.md`.
- [x] Re-run `make check` and record the fresh result in `notes.md`.
- [x] Run `git diff --check` and inspect the full branch diff.
- [ ] Reply to each owner-review thread with the specific code or documentation change and fresh verification evidence.
- [ ] Push the reviewed commits to PR #275. Do not deploy or merge.

## Review-revision coverage and self-review

- Combined daemon scheduling, connection lifetime, failure isolation, readiness, and shutdown: Task 6.
- System-wide read credential and driver-only mutation credentials: Task 6.
- Typed named GraphQL operations, exact fake dispatch, transaction clarity, and full-scan terminology: Task 7.
- Two-service examples, shared credential file, general runbook, and Simple English verification: Task 8.
- The immutable queue, normalization, one-pass poller semantics, queue-first reconciliation, scan fallback, source leases, and write manifest remain unchanged from Tasks 1–5.
- No task adds Docker, a remote broker, App-token refresh, an event-to-agent invocation path, a GitHub write surface, deployment action, or merge action.
