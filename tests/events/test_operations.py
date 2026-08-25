from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_sessions.events import operations
from agent_sessions.events.models import ApprovalWatch, Invalidation, RepositoryIdentity, VerifiedDelivery
from agent_sessions.events.store import CURRENT_SCHEMA_VERSION, QueueStore

NOW = datetime(2026, 8, 25, tzinfo=UTC)


def test_migrate_creates_a_database_and_doctor_reports_its_schema(tmp_path: Path, capsys) -> None:
    database = tmp_path / "events.sqlite3"
    assert operations.migrate(database, busy_timeout_ms=100) == 0
    assert "migrated: 1, 2" in capsys.readouterr().out
    assert operations.doctor(database, busy_timeout_ms=100) == 0
    assert "ready; schema=2" in capsys.readouterr().out


def test_doctor_refuses_an_incompatible_schema(tmp_path: Path, capsys) -> None:
    database = tmp_path / "events.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=100)
    connection = QueueStore.open(database, busy_timeout_ms=100).connection
    connection.execute("INSERT INTO schema_migrations VALUES (?, ?)", (CURRENT_SCHEMA_VERSION + 1, "now"))
    assert operations.doctor(database, busy_timeout_ms=100) == 1
    assert "not ready" in capsys.readouterr().out


def test_queue_status_renders_empty_human_and_json_values(tmp_path: Path, capsys) -> None:
    database = tmp_path / "events.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=100)
    store = QueueStore.open(database, busy_timeout_ms=100)
    store.register_repositories(())
    assert operations.queue_status(database, busy_timeout_ms=100, as_json=False, now=NOW) == 0
    human = capsys.readouterr().out
    assert "oldest-age=unknown" in human and "latest-delivery=never" in human
    assert operations.queue_status(database, busy_timeout_ms=100, as_json=True, now=NOW) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["backlog_count"] == 0 and payload["latest_delivery_at"] is None


def test_queue_status_reports_populated_projection_clocks_leases_ages_and_errors(tmp_path: Path, capsys) -> None:
    database = tmp_path / "events.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=100)
    store = QueueStore.open(database, busy_timeout_ms=100)
    store.register_repositories((RepositoryIdentity(1, "owner", "repo"),))
    observed = NOW - timedelta(seconds=120)
    store.enqueue_synthetic("scan", "hint", (Invalidation(1, "issue", "42", "observed"),), now=observed)
    failed = store.claim_targets(1, worker_id="retry", limit=1, lease_until=NOW, now=NOW)[0]
    store.retry(failed, error="temporary failure", next_attempt_at=NOW + timedelta(minutes=1))
    store.enqueue_synthetic("scan", "hint-2", (Invalidation(1, "issue", "43", "observed"),), now=NOW)
    store.claim_targets(1, worker_id="worker", limit=1, lease_until=NOW + timedelta(minutes=1), now=NOW)
    assert store.acquire_scan_lease(1, worker_id="scan", lease_until=NOW, now=NOW - timedelta(minutes=1))
    store.finish_scan(1, worker_id="scan", succeeded=True, now=NOW - timedelta(minutes=1))
    assert store.acquire_scan_lease(1, worker_id="scan", lease_until=NOW + timedelta(minutes=1), now=NOW)
    assert store.acquire_poller_lease("projects", worker_id="poll", lease_until=NOW, now=NOW - timedelta(minutes=1))
    store.finish_poller("projects", worker_id="poll", succeeded=True, now=NOW - timedelta(minutes=1))
    assert store.acquire_poller_lease("projects", worker_id="poll", lease_until=NOW, now=NOW - timedelta(seconds=30))
    store.finish_poller("projects", worker_id="poll", succeeded=False, now=NOW - timedelta(seconds=30), error="board timeout")
    assert store.acquire_poller_lease("projects", worker_id="poll", lease_until=NOW + timedelta(minutes=1), now=NOW)
    assert operations.queue_status(database, busy_timeout_ms=100, as_json=True, now=NOW) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["oldest_age_seconds"] == 120
    assert payload["repositories"] == [{
        "repository_id": 1,
        "last_hint_at": "2026-08-25T00:00:00+00:00",
        "last_scan_started_at": "2026-08-25T00:00:00+00:00",
        "last_scan_success_at": "2026-08-24T23:59:00+00:00",
        "last_scan_success_age_seconds": 60,
        "scan_lease_owner": "scan",
        "scan_lease_until": "2026-08-25T00:01:00+00:00",
    }]
    assert payload["pollers"] == [{
        "source_key": "projects",
        "last_success_at": "2026-08-24T23:59:00+00:00",
        "last_success_age_seconds": 60,
        "lease_owner": "poll",
        "lease_until": "2026-08-25T00:01:00+00:00",
        "last_error": "board timeout",
    }]
    assert set(payload["recent_errors"]) == {"temporary failure", "board timeout"}
    assert operations.queue_status(database, busy_timeout_ms=100, as_json=False, now=NOW) == 0
    human = capsys.readouterr().out
    assert "oldest-age=120s" in human
    assert "repository=1 last-hint=2026-08-25T00:00:00+00:00 scan-started=2026-08-25T00:00:00+00:00 scan-success=2026-08-24T23:59:00+00:00 scan-success-age=60s scan-lease=scan scan-lease-until=2026-08-25T00:01:00+00:00" in human
    assert "poller=projects last-success=2026-08-24T23:59:00+00:00 last-success-age=60s lease=poll lease-until=2026-08-25T00:01:00+00:00 last-error=board timeout" in human
    assert "recent-errors=" in human and "temporary failure" in human and "board timeout" in human


def test_prune_removes_expired_history_without_touching_live_scheduling_tables(tmp_path: Path, capsys) -> None:
    database = tmp_path / "events.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=100)
    store = QueueStore.open(database, busy_timeout_ms=100)
    store.register_repositories((RepositoryIdentity(1, "owner", "repo"),))
    historic = datetime(2026, 8, 1, tzinfo=UTC)
    store.enqueue_webhook(VerifiedDelivery("old", "issues", "edited", 1, b"{}", "accepted", {}), (Invalidation(1, "issue", "42", "old"),), now=historic)
    store.upsert_watch(ApprovalWatch(1, 42, "approved", NOW))
    assert operations.prune(database, busy_timeout_ms=100, deliveries_before=NOW, invalidations_before=NOW) == 0
    assert "deliveries=1 invalidations=1" in capsys.readouterr().out
    assert store.connection.execute("SELECT count(*) FROM dirty_targets").fetchone()[0] == 1
    assert store.connection.execute("SELECT count(*) FROM poll_watches").fetchone()[0] == 1


def test_cli_requires_config_when_not_provided(monkeypatch) -> None:
    from agent_sessions.events.cli import main

    monkeypatch.delenv("AGENT_SESSION_EVENTS_CONFIG", raising=False)
    with pytest.raises(SystemExit) as exited:
        main(["migrate"])
    assert exited.value.code == 2


def test_cli_uses_config_from_environment(tmp_path: Path, monkeypatch, capsys) -> None:
    from agent_sessions.events.cli import main

    database = tmp_path / "events.sqlite3"
    config = tmp_path / "events.toml"
    config.write_text(
        f'''database = "{database}"
busy_timeout_ms = 100
claim_limit = 1
claim_lease_seconds = 1
retry_base_seconds = 1
retry_max_seconds = 1
max_body_bytes = 1
delivery_retention_days = 1
invalidation_retention_days = 1
[scan]
quiet_period_seconds = 1
interval_seconds = 1
maximum_age_seconds = 1
[[repositories]]
id = 1
owner = "owner"
name = "repo"
[[boards]]
owner = "owner"
number = 1
repository_ids = [1]
''',
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_SESSION_EVENTS_CONFIG", str(config))
    assert main(["migrate"]) == 0
    assert "migrated: 1, 2" in capsys.readouterr().out
