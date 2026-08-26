"""SQLite-backed durable invalidation queue; every operation is local and short."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Iterable, Iterator, Literal, cast

from .models import (
    ApprovalWatch,
    ClaimedTarget,
    EnqueueResult,
    IncompatibleSchema,
    Invalidation,
    PollerStatus,
    ProjectItemProjection,
    PruneResult,
    QueueBusy,
    QueueStatus,
    QueueUnavailable,
    RepositoryIdentity,
    RepositoryStatus,
    StoreHealth,
    VerifiedDelivery,
)

MIGRATION_RESOURCES = (
    "001_queue.sql",
    "002_pollers.sql",
    "003_scan_errors.sql",
)
CURRENT_SCHEMA_VERSION = len(MIGRATION_RESOURCES)


def migration_scripts() -> tuple[str, ...]:
    """Return shipped schema migrations in their authoritative version order."""
    resources = files("agent_sessions.events.migrations")
    return tuple(resources.joinpath(name).read_text() for name in MIGRATION_RESOURCES)


def schema_shape_is_current(connection: sqlite3.Connection) -> bool:
    """Compare the live schema with the shape produced by shipped migrations."""
    expected = sqlite3.connect(":memory:")
    try:
        for script in migration_scripts():
            expected.executescript(script)
        expected_tables = {
            row[0]
            for row in expected.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        expected_shapes = {
            table: tuple(
                tuple(row)
                for row in expected.execute(f'PRAGMA table_info("{table}")')
            )
            for table in expected_tables
        }
        expected_foreign_keys = {
            table: tuple(
                tuple(row)
                for row in expected.execute(f'PRAGMA foreign_key_list("{table}")')
            )
            for table in expected_tables
        }

        def indexes(
            database: sqlite3.Connection, table: str
        ) -> frozenset[tuple[object, ...]]:
            result: set[tuple[object, ...]] = set()
            for row in database.execute(f'PRAGMA index_list("{table}")'):
                name = row[1]
                origin = row[3]
                columns = tuple(
                    (item[2], item[3], item[4], item[5])
                    for item in database.execute(f'PRAGMA index_xinfo("{name}")')
                )
                result.add(
                    (
                        name if origin == "c" else None,
                        row[2],
                        origin,
                        row[4],
                        columns,
                    )
                )
            return frozenset(result)

        expected_indexes = {
            table: indexes(expected, table) for table in expected_tables
        }
    finally:
        expected.close()

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if not expected_tables <= tables:
        return False
    for table, expected_columns in expected_shapes.items():
        columns = tuple(
            tuple(row)
            for row in connection.execute(f'PRAGMA table_info("{table}")')
        )
        if columns != expected_columns:
            return False
        foreign_keys = tuple(
            tuple(row)
            for row in connection.execute(f'PRAGMA foreign_key_list("{table}")')
        )
        if foreign_keys != expected_foreign_keys[table]:
            return False
        if indexes(connection, table) != expected_indexes[table]:
            return False
    return True


def _stamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _time(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value.replace("Z", "+00:00"))


def _required_time(value: str) -> datetime:
    parsed = _time(value)
    if parsed is None:  # pragma: no cover - NOT NULL columns cannot supply this
        raise ValueError("stored timestamp is missing")
    return parsed


def _queue_error(error: sqlite3.Error) -> QueueBusy | QueueUnavailable | None:
    if isinstance(error, sqlite3.OperationalError):
        if any(token in str(error).lower() for token in ("locked", "busy")):
            return QueueBusy("queue database is busy")
        return QueueUnavailable("queue database is unavailable")
    if isinstance(error, sqlite3.DatabaseError) and not isinstance(error, sqlite3.IntegrityError):
        return QueueUnavailable("queue database is unavailable")
    return None


def _raise_queue_error(error: sqlite3.Error) -> None:
    translated = _queue_error(error)
    if translated is None:
        raise error
    raise translated from error


class QueueStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def close(self) -> None:
        """Release this process-local connection after one poll pass."""
        self.connection.close()

    @staticmethod
    def _connect(path: Path, busy_timeout_ms: int) -> sqlite3.Connection:
        connection = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        return connection

    @classmethod
    def open(cls, path: Path, *, busy_timeout_ms: int) -> "QueueStore":
        connection = cls._connect(path, busy_timeout_ms)
        try:
            versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
        except sqlite3.Error as error:
            connection.close()
            raise IncompatibleSchema("database is not migrated") from error
        if versions != list(range(1, CURRENT_SCHEMA_VERSION + 1)) or not schema_shape_is_current(
            connection
        ):
            connection.close()
            raise IncompatibleSchema("database schema is incompatible")
        return cls(connection)

    @classmethod
    def migrate(cls, path: Path, *, busy_timeout_ms: int) -> tuple[int, ...]:
        path.parent.mkdir(parents=True, exist_ok=True)
        parent_mode = stat.S_IMODE(path.parent.stat().st_mode)
        shared_parent = (
            parent_mode & stat.S_ISGID
            and parent_mode & 0o077 == 0o070
        )
        database_mode = 0o660 if shared_parent else 0o600
        existed = path.exists()
        if not existed:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, database_mode)
            os.close(fd)
        os.chmod(path, database_mode)
        connection = cls._connect(path, busy_timeout_ms)
        try:
            connection.execute("BEGIN EXCLUSIVE")
            connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
            expected_prefix = set(range(1, max(applied, default=0) + 1))
            if applied != expected_prefix or any(version > CURRENT_SCHEMA_VERSION for version in applied):
                raise IncompatibleSchema("database schema is incompatible")
            changed: list[int] = []
            for version, sql in enumerate(migration_scripts(), start=1):
                if version in applied:
                    continue
                for statement in sql.split(";"):
                    if statement.strip():
                        connection.execute(statement)
                connection.execute("INSERT INTO schema_migrations VALUES (?, ?)", (version, _stamp(datetime.now(UTC))))
                changed.append(version)
            connection.commit()
            return tuple(changed)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def _transaction(self, mode: str = "IMMEDIATE") -> Iterator[sqlite3.Connection]:
        started = False
        try:
            self.connection.execute(f"BEGIN {mode}")
            started = True
            yield self.connection
            self.connection.commit()
        except Exception as error:
            if started:
                self._rollback_quietly()
            if isinstance(error, sqlite3.Error):
                _raise_queue_error(error)
            raise

    def _rollback_quietly(self) -> None:
        try:
            self.connection.rollback()
        except sqlite3.Error:
            pass

    def ready(self) -> StoreHealth:
        try:
            version = max((row[0] for row in self.connection.execute("SELECT version FROM schema_migrations")), default=None)
            ready = version == CURRENT_SCHEMA_VERSION and schema_shape_is_current(
                self.connection
            )
            return StoreHealth(
                ready,
                version,
                "" if ready else "incompatible schema",
            )
        except sqlite3.Error as error:
            return StoreHealth(False, None, str(error))

    def register_repositories(self, repositories: Iterable[RepositoryIdentity]) -> None:
        with self._transaction() as db:
            db.executemany(
                "INSERT INTO repository_state(repository_id,owner,name,installation_id) VALUES(?,?,?,?) ON CONFLICT(repository_id) DO UPDATE SET owner=excluded.owner,name=excluded.name,installation_id=excluded.installation_id",
                [(item.id, item.owner, item.name, item.installation_id) for item in repositories],
            )

    def _record_invalidations(self, db: sqlite3.Connection, source_kind: str, source_key: str, invalidations: Iterable[Invalidation], now: datetime) -> int:
        count = 0
        stamp = _stamp(now)
        for item in invalidations:
            diagnostic = json.dumps({"reason": item.reason, **item.diagnostic}, sort_keys=True)
            db.execute("INSERT INTO invalidations(source_kind,source_key,repository_id,target_kind,target_key,observed_at,diagnostic_json) VALUES(?,?,?,?,?,?,?)", (source_kind, source_key, item.repository_id, item.target_kind, item.target_key, stamp, diagnostic))
            db.execute("INSERT INTO dirty_targets(repository_id,target_kind,target_key,generation,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?) ON CONFLICT(repository_id,target_kind,target_key) DO UPDATE SET generation=dirty_targets.generation+1,last_seen_at=excluded.last_seen_at,lease_owner=NULL,lease_until=NULL,retry_count=0,next_attempt_at=NULL,last_error=NULL", (item.repository_id, item.target_kind, item.target_key, 1, stamp, stamp))
            db.execute("UPDATE repository_state SET last_hint_at=? WHERE repository_id=?", (stamp, item.repository_id))
            count += 1
        return count

    def enqueue_webhook(self, delivery: VerifiedDelivery, invalidations: Iterable[Invalidation], *, now: datetime) -> EnqueueResult:
        with self._transaction() as db:
            cursor = db.execute("INSERT OR IGNORE INTO webhook_deliveries VALUES(?,?,?,?,?,?,?,?)", (delivery.guid, delivery.event_type, delivery.action, delivery.repository_id, _stamp(now), delivery.disposition, delivery.raw_body, json.dumps(delivery.diagnostic, sort_keys=True)))
            if cursor.rowcount == 0:
                return EnqueueResult(True, 0)
            return EnqueueResult(False, self._record_invalidations(db, "webhook", delivery.guid, invalidations, now))

    def enqueue_synthetic(self, source_kind: str, source_key: str, invalidations: Iterable[Invalidation], *, now: datetime) -> int:
        with self._transaction() as db:
            return self._record_invalidations(db, source_kind, source_key, invalidations, now)

    def claim_targets(self, repository_id: int, *, worker_id: str, limit: int, lease_until: datetime, now: datetime) -> tuple[ClaimedTarget, ...]:
        with self._transaction() as db:
            rows = db.execute("SELECT repository_id,target_kind,target_key,generation,retry_count FROM dirty_targets WHERE repository_id=? AND (lease_until IS NULL OR lease_until<=?) AND (next_attempt_at IS NULL OR next_attempt_at<=?) ORDER BY first_seen_at LIMIT ?", (repository_id, _stamp(now), _stamp(now), limit)).fetchall()
            claims = tuple(ClaimedTarget(row["repository_id"], row["target_kind"], row["target_key"], row["generation"], worker_id, row["retry_count"]) for row in rows)
            db.executemany("UPDATE dirty_targets SET lease_owner=?,lease_until=? WHERE repository_id=? AND target_kind=? AND target_key=? AND generation=?", [(worker_id, _stamp(lease_until), claim.repository_id, claim.target_kind, claim.target_key, claim.generation) for claim in claims])
            return claims

    def _claim_update(self, claim: ClaimedTarget, sql: str, values: tuple[object, ...] = ()) -> bool:
        with self._transaction() as db:
            cursor = db.execute(sql, values + (claim.repository_id, claim.target_kind, claim.target_key, claim.generation, claim.lease_owner))
            return cursor.rowcount == 1

    def acknowledge(self, claim: ClaimedTarget) -> bool:
        return self._claim_update(claim, "DELETE FROM dirty_targets WHERE repository_id=? AND target_kind=? AND target_key=? AND generation=? AND lease_owner=?")

    def retry(self, claim: ClaimedTarget, *, error: str, next_attempt_at: datetime) -> bool:
        return self._claim_update(claim, "UPDATE dirty_targets SET lease_owner=NULL,lease_until=NULL,retry_count=retry_count+1,next_attempt_at=?,last_error=? WHERE repository_id=? AND target_kind=? AND target_key=? AND generation=? AND lease_owner=?", (_stamp(next_attempt_at), error))

    def release(self, claim: ClaimedTarget) -> bool:
        return self._claim_update(claim, "UPDATE dirty_targets SET lease_owner=NULL,lease_until=NULL WHERE repository_id=? AND target_kind=? AND target_key=? AND generation=? AND lease_owner=?")

    def acquire_scan_lease(self, repository_id: int, *, worker_id: str, lease_until: datetime, now: datetime) -> bool:
        with self._transaction() as db:
            cursor = db.execute("UPDATE repository_state SET scan_lease_owner=?,scan_lease_until=?,last_scan_started_at=? WHERE repository_id=? AND (scan_lease_until IS NULL OR scan_lease_until<=?)", (worker_id, _stamp(lease_until), _stamp(now), repository_id, _stamp(now)))
            return cursor.rowcount == 1

    def finish_scan(self, repository_id: int, *, worker_id: str, succeeded: bool, now: datetime, error: str = "") -> None:
        with self._transaction() as db:
            db.execute("UPDATE repository_state SET scan_lease_owner=NULL,scan_lease_until=NULL,last_scan_success_at=CASE WHEN ? THEN ? ELSE last_scan_success_at END,last_scan_error=CASE WHEN ? THEN '' ELSE ? END WHERE repository_id=? AND scan_lease_owner=?", (succeeded, _stamp(now), succeeded, error, repository_id, worker_id))

    def acquire_poller_lease(self, source_key: str, *, worker_id: str, lease_until: datetime, now: datetime) -> bool:
        with self._transaction() as db:
            db.execute("INSERT OR IGNORE INTO poller_state(source_key) VALUES(?)", (source_key,))
            cursor = db.execute("UPDATE poller_state SET lease_owner=?,lease_until=? WHERE source_key=? AND (lease_until IS NULL OR lease_until<=?)", (worker_id, _stamp(lease_until), source_key, _stamp(now)))
            return cursor.rowcount == 1

    def finish_poller(self, source_key: str, *, worker_id: str, succeeded: bool, now: datetime, error: str = "") -> None:
        with self._transaction() as db:
            db.execute("UPDATE poller_state SET lease_owner=NULL,lease_until=NULL,last_success_at=CASE WHEN ? THEN ? ELSE last_success_at END,last_error=? WHERE source_key=? AND lease_owner=?", (succeeded, _stamp(now), error, source_key, worker_id))

    @staticmethod
    def _poller_lease_is_current(
        db: sqlite3.Connection,
        source_key: str,
        worker_id: str,
        now: datetime,
    ) -> bool:
        return (
            db.execute(
                """SELECT 1 FROM poller_state
                WHERE source_key=? AND lease_owner=? AND lease_until>?""",
                (source_key, worker_id, _stamp(now)),
            ).fetchone()
            is not None
        )

    def poller_last_success_at(self, source_key: str) -> datetime | None:
        row = self.connection.execute(
            "SELECT last_success_at FROM poller_state WHERE source_key=?", (source_key,)
        ).fetchone()
        return None if row is None else _time(row[0])

    def upsert_watch(self, watch: ApprovalWatch) -> None:
        with self._transaction() as db:
            db.execute(
                """INSERT INTO poll_watches VALUES(?,?,?,?,?,?)
                ON CONFLICT(repository_id,issue_number,predicate) DO UPDATE SET
                  parked_at=excluded.parked_at,
                  last_value=CASE
                    WHEN poll_watches.parked_at<>excluded.parked_at THEN excluded.last_value
                    ELSE poll_watches.last_value
                  END,
                  last_checked_at=CASE
                    WHEN poll_watches.parked_at<>excluded.parked_at THEN excluded.last_checked_at
                    ELSE poll_watches.last_checked_at
                  END""",
                (
                    watch.repository_id,
                    watch.issue_number,
                    watch.predicate,
                    _stamp(watch.parked_at),
                    None if watch.last_value is None else int(watch.last_value),
                    None
                    if watch.last_checked_at is None
                    else _stamp(watch.last_checked_at),
                ),
            )

    def remove_watch(self, repository_id: int, issue_number: int) -> None:
        with self._transaction() as db:
            db.execute("DELETE FROM poll_watches WHERE repository_id=? AND issue_number=?", (repository_id, issue_number))

    def list_watches(self, repository_id: int) -> tuple[ApprovalWatch, ...]:
        return tuple(ApprovalWatch(row["repository_id"], row["issue_number"], row["predicate"], _time(row["parked_at"]), None if row["last_value"] is None else bool(row["last_value"]), _time(row["last_checked_at"])) for row in self.connection.execute("SELECT * FROM poll_watches WHERE repository_id=? ORDER BY issue_number", (repository_id,)))  # type: ignore[arg-type]

    def _record_watch_observation(
        self,
        db: sqlite3.Connection,
        watch: ApprovalWatch,
        *,
        value: bool,
        observed_at: datetime,
    ) -> bool | None:
        parked_at = _stamp(watch.parked_at)
        expected_value = None if watch.last_value is None else int(watch.last_value)
        expected_checked_at = (
            None if watch.last_checked_at is None else _stamp(watch.last_checked_at)
        )
        changed = watch.last_value is not None and watch.last_value != value
        cursor = db.execute(
            """UPDATE poll_watches SET last_value=?,last_checked_at=?
            WHERE repository_id=? AND issue_number=? AND predicate=? AND parked_at=?
              AND last_value IS ? AND last_checked_at IS ?""",
            (
                int(value),
                _stamp(observed_at),
                watch.repository_id,
                watch.issue_number,
                watch.predicate,
                parked_at,
                expected_value,
                expected_checked_at,
            ),
        )
        if cursor.rowcount != 1:
            return None
        if changed:
            self._record_invalidations(
                db,
                "reaction_observation",
                f"reactions:{watch.repository_id}",
                (
                    Invalidation(
                        watch.repository_id,
                        "issue",
                        str(watch.issue_number),
                        "approval_predicate_changed",
                        {"predicate": watch.predicate, "value": value},
                    ),
                ),
                observed_at,
            )
        return changed

    def record_watch_observation(
        self,
        watch: ApprovalWatch,
        *,
        value: bool,
        observed_at: datetime,
    ) -> bool:
        with self._transaction() as db:
            changed = self._record_watch_observation(
                db,
                watch,
                value=value,
                observed_at=observed_at,
            )
            return False if changed is None else changed

    def record_watch_observation_if_leased(
        self,
        source_key: str,
        *,
        worker_id: str,
        watch: ApprovalWatch,
        value: bool,
        observed_at: datetime,
    ) -> bool | None:
        with self._transaction() as db:
            if not self._poller_lease_is_current(
                db, source_key, worker_id, observed_at
            ):
                return None
            return self._record_watch_observation(
                db,
                watch,
                value=value,
                observed_at=observed_at,
            )

    def replace_project_snapshot(
        self,
        board_key: str,
        projections: Iterable[ProjectItemProjection],
        invalidations: Iterable[Invalidation],
        *,
        now: datetime,
    ) -> None:
        with self._transaction() as db:
            self._replace_project_snapshot(
                db, board_key, projections, invalidations, now=now
            )

    def _replace_project_snapshot(
        self,
        db: sqlite3.Connection,
        board_key: str,
        projections: Iterable[ProjectItemProjection],
        invalidations: Iterable[Invalidation],
        *,
        now: datetime,
    ) -> None:
        db.execute("DELETE FROM project_items WHERE board_key=?", (board_key,))
        db.executemany(
            "INSERT INTO project_items VALUES(?,?,?,?,?,?,?,?)",
            [
                (
                    item.board_key,
                    item.item_node_id,
                    item.repository_id,
                    item.content_kind,
                    item.content_number,
                    item.status,
                    item.priority,
                    _stamp(item.last_seen_at),
                )
                for item in projections
            ],
        )
        self._record_invalidations(
            db,
            "project_snapshot",
            f"projects:{board_key}",
            invalidations,
            now,
        )

    def replace_project_snapshot_if_leased(
        self,
        source_key: str,
        *,
        worker_id: str,
        board_key: str,
        projections: Iterable[ProjectItemProjection],
        invalidations: Iterable[Invalidation],
        now: datetime,
    ) -> bool:
        with self._transaction() as db:
            if not self._poller_lease_is_current(db, source_key, worker_id, now):
                return False
            self._replace_project_snapshot(
                db, board_key, projections, invalidations, now=now
            )
            return True

    def project_snapshot(self, board_key: str) -> tuple[ProjectItemProjection, ...]:
        return tuple(
            ProjectItemProjection(
                row["board_key"],
                row["item_node_id"],
                row["repository_id"],
                cast(Literal["issue", "pull_request"], row["content_kind"]),
                row["content_number"],
                row["status"],
                row["priority"],
                _required_time(row["last_seen_at"]),
            )
            for row in self.connection.execute(
                "SELECT * FROM project_items WHERE board_key=? ORDER BY item_node_id",
                (board_key,),
            )
        )

    def status(self, *, now: datetime) -> QueueStatus:
        backlog, oldest, leased, backed = self.connection.execute("SELECT count(*),min(first_seen_at),sum(lease_until IS NOT NULL AND lease_until>?),sum(next_attempt_at IS NOT NULL AND next_attempt_at>?) FROM dirty_targets", (_stamp(now), _stamp(now))).fetchone()
        latest = self.connection.execute("SELECT max(received_at) FROM webhook_deliveries").fetchone()[0]
        repositories = tuple(RepositoryStatus(row["repository_id"], _time(row["last_hint_at"]), _time(row["last_scan_started_at"]), _time(row["last_scan_success_at"]), row["scan_lease_owner"], _time(row["scan_lease_until"]), row["last_scan_error"] or "") for row in self.connection.execute("SELECT * FROM repository_state ORDER BY repository_id"))
        pollers = tuple(PollerStatus(row["source_key"], _time(row["last_success_at"]), row["lease_owner"], _time(row["lease_until"]), row["last_error"] or "") for row in self.connection.execute("SELECT * FROM poller_state ORDER BY source_key"))
        errors = tuple(row[0] for row in self.connection.execute("SELECT last_scan_error FROM repository_state WHERE last_scan_error <> '' UNION ALL SELECT last_error FROM poller_state WHERE last_error <> '' UNION ALL SELECT last_error FROM dirty_targets WHERE last_error IS NOT NULL ORDER BY 1 DESC LIMIT 10"))
        return QueueStatus(CURRENT_SCHEMA_VERSION, backlog, _time(oldest), leased or 0, backed or 0, _time(latest), repositories, pollers, self.connection.execute("SELECT count(*) FROM poll_watches").fetchone()[0], errors)

    def prune(self, *, deliveries_before: datetime, invalidations_before: datetime) -> PruneResult:
        with self._transaction() as db:
            deliveries = db.execute("DELETE FROM webhook_deliveries WHERE received_at < ?", (_stamp(deliveries_before),)).rowcount
            invalidations = db.execute("DELETE FROM invalidations WHERE observed_at < ?", (_stamp(invalidations_before),)).rowcount
        busy, log, checkpointed = self.connection.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        return PruneResult(deliveries, invalidations, busy, log, checkpointed)
