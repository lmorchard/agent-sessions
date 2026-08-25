from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_sessions.events.driver import RepositoryScanState, scan_decision
from agent_sessions.events.models import RepositoryIdentity, ScanPolicy
from agent_sessions.events.store import QueueStore

NOW = datetime(2026, 8, 25, 12, tzinfo=UTC)
POLICY = ScanPolicy(
    quiet_period=timedelta(minutes=5),
    interval=timedelta(minutes=15),
    maximum_age=timedelta(hours=1),
)


def state(
    *,
    last_hint_at: datetime | None = None,
    last_scan_success_at: datetime | None = NOW,
) -> RepositoryScanState:
    return RepositoryScanState(
        last_hint_at=last_hint_at,
        last_scan_success_at=last_scan_success_at,
        scan_lease_owner=None,
        scan_lease_until=None,
    )


def test_never_scanned_repository_reaches_the_hard_deadline() -> None:
    assert (
        scan_decision(
            now=NOW,
            state=state(last_scan_success_at=None),
            has_immediately_eligible_target=False,
            policy=POLICY,
        )
        == "hard-deadline"
    )


def test_hard_maximum_age_takes_priority_over_dirty_work() -> None:
    assert (
        scan_decision(
            now=NOW,
            state=state(last_scan_success_at=NOW - POLICY.maximum_age),
            has_immediately_eligible_target=True,
            policy=POLICY,
        )
        == "hard-deadline"
    )


def test_immediately_eligible_dirty_work_suppresses_normal_scan() -> None:
    assert (
        scan_decision(
            now=NOW,
            state=state(last_scan_success_at=NOW - POLICY.interval),
            has_immediately_eligible_target=True,
            policy=POLICY,
        )
        == "not-due"
    )


def test_recent_hint_suppresses_normal_scan_during_quiet_period() -> None:
    assert (
        scan_decision(
            now=NOW,
            state=state(
                last_hint_at=NOW - POLICY.quiet_period + timedelta(seconds=1),
                last_scan_success_at=NOW - POLICY.interval,
            ),
            has_immediately_eligible_target=False,
            policy=POLICY,
        )
        == "not-due"
    )


def test_normal_interval_scan_runs_after_the_repository_is_quiet() -> None:
    assert (
        scan_decision(
            now=NOW,
            state=state(
                last_hint_at=NOW - POLICY.quiet_period,
                last_scan_success_at=NOW - POLICY.interval,
            ),
            has_immediately_eligible_target=False,
            policy=POLICY,
        )
        == "quiet-period"
    )


def test_repository_scan_lease_excludes_overlapping_scans(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    QueueStore.migrate(database, busy_timeout_ms=50)
    first = QueueStore.open(database, busy_timeout_ms=50)
    second = QueueStore.open(database, busy_timeout_ms=50)
    first.register_repositories((RepositoryIdentity(1, "owner", "repo"),))

    assert first.acquire_scan_lease(
        1,
        worker_id="first",
        lease_until=NOW + timedelta(minutes=5),
        now=NOW,
    )
    assert not second.acquire_scan_lease(
        1,
        worker_id="second",
        lease_until=NOW + timedelta(minutes=5),
        now=NOW,
    )
