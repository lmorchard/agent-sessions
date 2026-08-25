from __future__ import annotations

import sqlite3
import stat
import threading
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path

import pytest

from agent_sessions.events import store as store_module
from agent_sessions.events.models import (
    ApprovalWatch,
    Invalidation,
    ProjectItemProjection,
    QueueBusy,
    RepositoryIdentity,
    VerifiedDelivery,
)
from agent_sessions.events.store import CURRENT_SCHEMA_VERSION, IncompatibleSchema, QueueStore

NOW = datetime(2026, 8, 25, tzinfo=UTC)


def invalidation(key: str = "42") -> Invalidation:
    return Invalidation(1, "issue", key, "test")


def delivery(guid: str = "guid") -> VerifiedDelivery:
    return VerifiedDelivery(guid, "issues", "edited", 1, b"{}", "accepted", {})


def migrated(tmp_path: Path) -> QueueStore:
    path = tmp_path / "events.sqlite3"
    assert QueueStore.migrate(path, busy_timeout_ms=250) == (1, 2)
    store = QueueStore.open(path, busy_timeout_ms=250)
    store.register_repositories((RepositoryIdentity(1, "owner", "repo"),))
    return store


def test_migrate_creates_private_wal_foreign_key_database(tmp_path: Path) -> None:
    path = tmp_path / "events.sqlite3"
    assert QueueStore.migrate(path, busy_timeout_ms=321) == (1, 2)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    store = QueueStore.open(path, busy_timeout_ms=321)
    assert store.ready().schema_version == CURRENT_SCHEMA_VERSION
    assert store.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert store.connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert store.connection.execute("PRAGMA busy_timeout").fetchone()[0] == 321


def test_open_refuses_an_ahead_schema(tmp_path: Path) -> None:
    path = tmp_path / "events.sqlite3"
    QueueStore.migrate(path, busy_timeout_ms=10)
    connection = sqlite3.connect(path)
    connection.execute("INSERT INTO schema_migrations VALUES (?, ?)", (CURRENT_SCHEMA_VERSION + 1, "now"))
    connection.commit()
    connection.close()
    with pytest.raises(IncompatibleSchema):
        QueueStore.open(path, busy_timeout_ms=10)


def test_migrate_refuses_an_ahead_schema_without_applying_more_migrations(tmp_path: Path) -> None:
    path = tmp_path / "events.sqlite3"
    QueueStore.migrate(path, busy_timeout_ms=10)
    connection = sqlite3.connect(path)
    connection.execute("INSERT INTO schema_migrations VALUES (?, ?)", (CURRENT_SCHEMA_VERSION + 1, "now"))
    connection.commit()
    connection.close()
    with pytest.raises(IncompatibleSchema):
        QueueStore.migrate(path, busy_timeout_ms=10)
    assert sqlite3.connect(path).execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == CURRENT_SCHEMA_VERSION + 1


def test_migrates_a_database_at_schema_version_one(tmp_path: Path) -> None:
    path = tmp_path / "events.sqlite3"
    connection = sqlite3.connect(path)
    for statement in files("agent_sessions.events.migrations").joinpath("001_queue.sql").read_text().split(";"):
        if statement.strip():
            connection.execute(statement)
    connection.execute("INSERT INTO schema_migrations VALUES (1, '2026-08-25T00:00:00Z')")
    connection.commit()
    connection.close()
    assert QueueStore.migrate(path, busy_timeout_ms=10) == (2,)
    assert QueueStore.open(path, busy_timeout_ms=10).ready().schema_version == CURRENT_SCHEMA_VERSION


def test_migrates_legacy_version_one_delivery_fk_and_retains_unconfigured_delivery(tmp_path: Path) -> None:
    path = tmp_path / "events.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
        CREATE TABLE repository_state (repository_id INTEGER PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL, installation_id INTEGER, last_hint_at TEXT, last_scan_started_at TEXT, last_scan_success_at TEXT, scan_lease_owner TEXT, scan_lease_until TEXT);
        CREATE TABLE webhook_deliveries (delivery_guid TEXT PRIMARY KEY, event_type TEXT NOT NULL, action TEXT NOT NULL, repository_id INTEGER, received_at TEXT NOT NULL, disposition TEXT NOT NULL, raw_body BLOB NOT NULL, diagnostic_json TEXT NOT NULL, FOREIGN KEY(repository_id) REFERENCES repository_state(repository_id));
        CREATE TABLE invalidations (id INTEGER PRIMARY KEY AUTOINCREMENT, source_kind TEXT NOT NULL, source_key TEXT NOT NULL, repository_id INTEGER NOT NULL, target_kind TEXT NOT NULL, target_key TEXT NOT NULL, observed_at TEXT NOT NULL, diagnostic_json TEXT NOT NULL, FOREIGN KEY(repository_id) REFERENCES repository_state(repository_id));
        CREATE TABLE dirty_targets (repository_id INTEGER NOT NULL, target_kind TEXT NOT NULL, target_key TEXT NOT NULL, generation INTEGER NOT NULL, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, lease_owner TEXT, lease_until TEXT, retry_count INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT, last_error TEXT, PRIMARY KEY(repository_id, target_kind, target_key), FOREIGN KEY(repository_id) REFERENCES repository_state(repository_id));
        CREATE INDEX invalidations_retention_idx ON invalidations(observed_at);
        CREATE INDEX deliveries_retention_idx ON webhook_deliveries(received_at);
        CREATE INDEX dirty_claim_idx ON dirty_targets(repository_id, lease_until, next_attempt_at);
        CREATE INDEX repository_status_idx ON repository_state(last_hint_at, last_scan_success_at);
        """
    )
    connection.execute("INSERT INTO schema_migrations VALUES (1, '2026-08-25T00:00:00Z')")
    connection.commit()
    connection.close()
    assert QueueStore.migrate(path, busy_timeout_ms=10) == (2,)
    store = QueueStore.open(path, busy_timeout_ms=10)
    ignored = VerifiedDelivery("legacy-ignored", "issues", "edited", 999, b"{}", "ignored_unconfigured", {})
    assert store.enqueue_webhook(ignored, (), now=NOW).duplicate is False
    assert store.connection.execute("SELECT repository_id FROM webhook_deliveries").fetchone()[0] == 999
    assert store.connection.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='deliveries_retention_idx'").fetchone()[0] == "deliveries_retention_idx"


def test_failing_migration_rolls_back_every_schema_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "events.sqlite3"
    real_files = store_module.files

    class BrokenResources:
        def joinpath(self, name: str):
            if name == "002_pollers.sql":
                return type("BrokenSql", (), {"read_text": lambda self: "CREATE TABLE broken ("})()
            return real_files("agent_sessions.events.migrations").joinpath(name)

    monkeypatch.setattr(store_module, "files", lambda _package: BrokenResources())
    with pytest.raises(sqlite3.OperationalError):
        QueueStore.migrate(path, busy_timeout_ms=10)
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='repository_state'").fetchone() is None
    connection.close()


def test_delivery_enqueue_is_atomic_and_duplicate_is_a_noop(tmp_path: Path) -> None:
    store = migrated(tmp_path)
    result = store.enqueue_webhook(delivery(), (invalidation(),), now=NOW)
    assert result.duplicate is False and result.invalidation_count == 1
    assert store.enqueue_webhook(delivery(), (invalidation("other"),), now=NOW).duplicate is True
    assert store.connection.execute("SELECT count(*) FROM invalidations").fetchone()[0] == 1
    assert store.connection.execute("SELECT generation FROM dirty_targets").fetchone()[0] == 1


def test_locked_database_translates_to_queue_busy_without_committing(tmp_path: Path) -> None:
    store = migrated(tmp_path)
    locker = sqlite3.connect(tmp_path / "events.sqlite3", isolation_level=None)
    locker.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(QueueBusy) as raised:
            store.enqueue_webhook(delivery(), (invalidation(),), now=NOW)
    finally:
        locker.rollback()
        locker.close()

    assert isinstance(raised.value.__cause__, sqlite3.OperationalError)
    assert store.connection.execute("SELECT count(*) FROM webhook_deliveries").fetchone()[0] == 0


def test_ignored_unconfigured_webhook_delivery_is_retained_without_a_dirty_target(tmp_path: Path) -> None:
    store = migrated(tmp_path)
    ignored = VerifiedDelivery("ignored", "issues", "edited", 999, b"{}", "ignored_unconfigured", {})
    assert store.enqueue_webhook(ignored, (), now=NOW).duplicate is False
    assert store.connection.execute("SELECT repository_id, disposition FROM webhook_deliveries").fetchone()[:] == (999, "ignored_unconfigured")
    assert store.connection.execute("SELECT count(*) FROM dirty_targets").fetchone()[0] == 0


def test_new_generation_survives_acknowledgement_of_older_claim(tmp_path: Path) -> None:
    store = migrated(tmp_path)
    store.enqueue_webhook(delivery(), (invalidation(),), now=NOW)
    claim = store.claim_targets(1, worker_id="one", limit=1, lease_until=NOW + timedelta(minutes=5), now=NOW)[0]
    store.enqueue_webhook(delivery("new"), (invalidation(),), now=NOW + timedelta(seconds=1))
    assert store.acknowledge(claim) is False
    assert store.connection.execute("SELECT generation FROM dirty_targets").fetchone()[0] == 2


def test_claims_and_backoff_are_conditional_and_expired_leases_recover(tmp_path: Path) -> None:
    store = migrated(tmp_path)
    store.enqueue_synthetic("scan", "first", (invalidation(),), now=NOW)
    store.claim_targets(1, worker_id="one", limit=1, lease_until=NOW + timedelta(seconds=1), now=NOW)[0]
    assert store.claim_targets(1, worker_id="two", limit=1, lease_until=NOW, now=NOW) == ()
    recovered = store.claim_targets(1, worker_id="two", limit=1, lease_until=NOW + timedelta(minutes=1), now=NOW + timedelta(seconds=2))[0]
    assert recovered.lease_owner == "two"
    assert store.retry(recovered, error="temporary", next_attempt_at=NOW + timedelta(hours=1))
    assert store.claim_targets(1, worker_id="three", limit=1, lease_until=NOW, now=NOW + timedelta(minutes=2)) == ()
    store.enqueue_synthetic("scan", "second", (invalidation(),), now=NOW + timedelta(minutes=3))
    assert store.claim_targets(1, worker_id="three", limit=1, lease_until=NOW + timedelta(hours=1), now=NOW + timedelta(minutes=3))


def test_two_simultaneous_consumers_receive_disjoint_claims(tmp_path: Path) -> None:
    store = migrated(tmp_path)
    store.enqueue_synthetic("scan", "first", (invalidation("42"), invalidation("43")), now=NOW)
    other = QueueStore.open(tmp_path / "events.sqlite3", busy_timeout_ms=250)
    start = threading.Barrier(2)
    claims: list[tuple] = []

    def claim_from(candidate: QueueStore, worker_id: str) -> None:
        start.wait()
        claims.append(candidate.claim_targets(1, worker_id=worker_id, limit=1, lease_until=NOW + timedelta(minutes=1), now=NOW))

    first = threading.Thread(target=claim_from, args=(store, "one"))
    second = threading.Thread(target=claim_from, args=(other, "two"))
    first.start()
    second.start()
    first.join()
    second.join()
    claimed = [claim for group in claims for claim in group]
    assert len(claimed) == 2
    assert {(claim.target_kind, claim.target_key) for claim in claimed} == {("issue", "42"), ("issue", "43")}


def test_leases_watches_snapshots_and_pruning_preserve_live_tables(tmp_path: Path) -> None:
    store = migrated(tmp_path)
    assert store.acquire_scan_lease(1, worker_id="scan", lease_until=NOW + timedelta(minutes=1), now=NOW)
    assert not store.acquire_scan_lease(1, worker_id="other", lease_until=NOW, now=NOW)
    assert store.acquire_poller_lease("board", worker_id="poll", lease_until=NOW + timedelta(minutes=1), now=NOW)
    watch = ApprovalWatch(1, 42, "approved", NOW)
    store.upsert_watch(watch)
    assert not store.record_watch_observation(watch, value=True, observed_at=NOW)
    assert store.record_watch_observation(watch, value=False, observed_at=NOW + timedelta(seconds=1))
    projection = ProjectItemProjection("owner/9", "item", 1, "issue", 42, "Ready", None, NOW)
    store.replace_project_snapshot("owner/9", (projection,), (invalidation(),), now=NOW)
    store.enqueue_webhook(delivery(), (invalidation("43"),), now=NOW - timedelta(days=2))
    result = store.prune(deliveries_before=NOW - timedelta(days=1), invalidations_before=NOW - timedelta(days=1))
    assert result.deliveries_deleted == 1
    assert store.connection.execute("SELECT count(*) FROM project_items").fetchone()[0] == 1
    assert store.connection.execute("SELECT count(*) FROM poll_watches").fetchone()[0] == 1
    assert store.connection.execute("SELECT count(*) FROM poller_state").fetchone()[0] == 1


def test_watches_list_remove_and_only_invalidate_on_a_changed_observation(tmp_path: Path) -> None:
    store = migrated(tmp_path)
    first = ApprovalWatch(1, 42, "approved", NOW)
    second = ApprovalWatch(1, 43, "approved", NOW)
    store.upsert_watch(first)
    store.upsert_watch(second)
    assert tuple(watch.issue_number for watch in store.list_watches(1)) == (42, 43)
    assert not store.record_watch_observation(first, value=True, observed_at=NOW)
    assert not store.record_watch_observation(first, value=True, observed_at=NOW + timedelta(seconds=1))
    assert store.record_watch_observation(first, value=False, observed_at=NOW + timedelta(seconds=2))
    store.remove_watch(1, 42)
    assert tuple(watch.issue_number for watch in store.list_watches(1)) == (43,)


def test_scan_and_poller_leases_exclude_other_workers_and_record_success_only_when_finished(tmp_path: Path) -> None:
    store = migrated(tmp_path)
    assert store.acquire_scan_lease(1, worker_id="scan", lease_until=NOW + timedelta(minutes=1), now=NOW)
    assert not store.acquire_scan_lease(1, worker_id="other", lease_until=NOW + timedelta(minutes=1), now=NOW)
    store.finish_scan(1, worker_id="scan", succeeded=False, now=NOW, error="rate limited")
    state = store.status(now=NOW).repositories[0]
    assert state.last_scan_success_at is None and state.scan_lease_owner is None
    assert store.acquire_poller_lease("reactions", worker_id="poll", lease_until=NOW + timedelta(minutes=1), now=NOW)
    assert not store.acquire_poller_lease("reactions", worker_id="other", lease_until=NOW + timedelta(minutes=1), now=NOW)
    store.finish_poller("reactions", worker_id="poll", succeeded=True, now=NOW)
    poller = store.status(now=NOW).pollers[0]
    assert poller.last_success_at == NOW and poller.lease_owner is None


def test_snapshot_replacement_rolls_back_if_its_invalidation_cannot_be_persisted(tmp_path: Path) -> None:
    store = migrated(tmp_path)
    original = ProjectItemProjection("owner/9", "old", 1, "issue", 42, "Ready", None, NOW)
    store.replace_project_snapshot("owner/9", (original,), (), now=NOW)
    replacement = ProjectItemProjection("owner/9", "new", 1, "issue", 43, "Done", None, NOW)
    bad = Invalidation(999, "issue", "44", "missing repository")
    with pytest.raises(sqlite3.IntegrityError):
        store.replace_project_snapshot("owner/9", (replacement,), (bad,), now=NOW)
    assert store.connection.execute("SELECT item_node_id FROM project_items").fetchone()[0] == "old"


def test_synthetic_invalidations_keep_source_provenance(tmp_path: Path) -> None:
    store = migrated(tmp_path)
    assert store.enqueue_synthetic("poller", "board:owner/9", (invalidation(),), now=NOW) == 1
    row = store.connection.execute("SELECT source_kind, source_key FROM invalidations").fetchone()
    assert tuple(row) == ("poller", "board:owner/9")
