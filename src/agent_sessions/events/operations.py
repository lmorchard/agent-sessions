"""Database-only commands for local queue operations."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .models import IncompatibleSchema
from .store import QueueStore


def _timestamp(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _age_seconds(value: datetime | None, now: datetime) -> int | None:
    return None if value is None else max(0, int((now - value).total_seconds()))


def migrate(database: Path, *, busy_timeout_ms: int) -> int:
    versions = QueueStore.migrate(database, busy_timeout_ms=busy_timeout_ms)
    print("migrated: " + (", ".join(map(str, versions)) if versions else "already current"))
    return 0


def doctor(database: Path, *, busy_timeout_ms: int) -> int:
    try:
        health = QueueStore.open(database, busy_timeout_ms=busy_timeout_ms).ready()
    except IncompatibleSchema as error:
        print(f"database: not ready ({error})")
        return 1
    print(f"database: {'ready' if health.ready else 'not ready'}; schema={health.schema_version}")
    return 0 if health.ready else 1


def queue_status(database: Path, *, busy_timeout_ms: int, as_json: bool, now: datetime) -> int:
    status = QueueStore.open(database, busy_timeout_ms=busy_timeout_ms).status(now=now)
    values = {
        "schema_version": status.schema_version,
        "backlog_count": status.backlog_count,
        "oldest_dirty_at": _timestamp(status.oldest_dirty_at),
        "oldest_age_seconds": _age_seconds(status.oldest_dirty_at, now),
        "leased_count": status.leased_count,
        "backed_off_count": status.backed_off_count,
        "latest_delivery_at": _timestamp(status.latest_delivery_at),
        "watch_count": status.watch_count,
        "recent_errors": list(status.recent_errors),
        "repositories": [
            {
                "repository_id": item.repository_id,
                "last_hint_at": _timestamp(item.last_hint_at),
                "last_scan_started_at": _timestamp(item.last_scan_started_at),
                "last_scan_success_at": _timestamp(item.last_scan_success_at),
                "last_scan_success_age_seconds": _age_seconds(item.last_scan_success_at, now),
                "scan_lease_owner": item.scan_lease_owner,
                "scan_lease_until": _timestamp(item.scan_lease_until),
            }
            for item in status.repositories
        ],
        "pollers": [
            {
                "source_key": item.source_key,
                "last_success_at": _timestamp(item.last_success_at),
                "last_success_age_seconds": _age_seconds(item.last_success_at, now),
                "lease_owner": item.lease_owner,
                "lease_until": _timestamp(item.lease_until),
                "last_error": item.last_error,
            }
            for item in status.pollers
        ],
    }
    if as_json:
        print(json.dumps(values, sort_keys=True))
    else:
        oldest = "unknown" if values["oldest_age_seconds"] is None else f"{values['oldest_age_seconds']}s"
        latest = "never" if status.latest_delivery_at is None else status.latest_delivery_at.isoformat()
        print(f"backlog={status.backlog_count} oldest-age={oldest} leases={status.leased_count} backoff={status.backed_off_count} latest-delivery={latest} watches={status.watch_count} schema={status.schema_version}")
        for repository in status.repositories:
            last_hint = _timestamp(repository.last_hint_at) or "unknown"
            scan_started = _timestamp(repository.last_scan_started_at) or "never"
            scan_success = _timestamp(repository.last_scan_success_at) or "never"
            scan_success_age = _age_seconds(repository.last_scan_success_at, now)
            scan_lease = repository.scan_lease_owner or "none"
            scan_lease_until = _timestamp(repository.scan_lease_until) or "never"
            age = "unknown" if scan_success_age is None else f"{scan_success_age}s"
            print(f"repository={repository.repository_id} last-hint={last_hint} scan-started={scan_started} scan-success={scan_success} scan-success-age={age} scan-lease={scan_lease} scan-lease-until={scan_lease_until}")
        for poller in status.pollers:
            success = _timestamp(poller.last_success_at) or "never"
            success_age = _age_seconds(poller.last_success_at, now)
            lease = poller.lease_owner or "none"
            lease_until = _timestamp(poller.lease_until) or "never"
            age = "unknown" if success_age is None else f"{success_age}s"
            error = poller.last_error or "none"
            print(f"poller={poller.source_key} last-success={success} last-success-age={age} lease={lease} lease-until={lease_until} last-error={error}")
        print(f"recent-errors={'; '.join(status.recent_errors) if status.recent_errors else 'none'}")
    return 0


def prune(database: Path, *, busy_timeout_ms: int, deliveries_before: datetime, invalidations_before: datetime) -> int:
    result = QueueStore.open(database, busy_timeout_ms=busy_timeout_ms).prune(deliveries_before=deliveries_before, invalidations_before=invalidations_before)
    print(f"pruned deliveries={result.deliveries_deleted} invalidations={result.invalidations_deleted}")
    return 0
