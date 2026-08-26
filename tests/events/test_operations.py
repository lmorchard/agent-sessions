from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from agent_sessions.events import operations
from agent_sessions.events.models import ApprovalWatch, Invalidation, RepositoryIdentity, VerifiedDelivery
from agent_sessions.events.store import CURRENT_SCHEMA_VERSION, QueueStore

NOW = datetime(2026, 8, 25, tzinfo=UTC)


def _write_config(
    path: Path,
    database: Path,
    *,
    repositories: str = '''[[repositories]]
id = 1
owner = "owner"
name = "repo"
''',
    boards: str = '''[[boards]]
owner = "owner"
number = 1
repository_ids = [1]
''',
) -> None:
    path.write_text(
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
[polling]
projects_interval_seconds = 60
reactions_interval_seconds = 60
{repositories}
{boards}
''',
        encoding="utf-8",
    )


def _successful_doctor_runner(
    command: list[str], **kwargs: Any
) -> subprocess.CompletedProcess[str]:
    assert command[:2] != ["gh", "issue"]
    assert command[:2] != ["gh", "pr"]
    assert "--method" not in command
    env = kwargs["env"]
    assert env["GH_TOKEN"] == env["GITHUB_TOKEN"]
    endpoint = command[2] if command[:2] == ["gh", "api"] else ""
    payload: object
    if endpoint == "repos/owner/repo":
        payload = {"id": 1, "full_name": "owner/repo"}
    elif endpoint == "repos/owner/repo/commits?per_page=1":
        payload = [{"sha": "a" * 40}]
    elif endpoint == f"repos/owner/repo/commits/{'a' * 40}/check-runs":
        payload = {"total_count": 0, "check_runs": []}
    elif endpoint == f"repos/owner/repo/commits/{'a' * 40}/status":
        payload = {"sha": "a" * 40, "state": "pending", "statuses": []}
    elif command[:3] == ["gh", "project", "field-list"]:
        payload = {
            "fields": [{"name": "Status"}, {"name": "Priority"}],
            "totalCount": 2,
        }
    else:
        raise AssertionError(f"unexpected doctor command: {command}")
    return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")


def _doctor_report(
    config_path: Path,
    *,
    environ: dict[str, str] | None = None,
    runner=_successful_doctor_runner,
):
    return operations.inspect_doctor(
        config_path,
        environ={} if environ is None else environ,
        runner=runner,
        read_credential_resolver=lambda _: "read-credential-value",
    )


def test_migrate_creates_a_database_and_doctor_reports_its_schema(tmp_path: Path, capsys) -> None:
    database = tmp_path / "events.sqlite3"
    config_path = tmp_path / "events.toml"
    _write_config(config_path, database)
    assert operations.migrate(database, busy_timeout_ms=100) == 0
    assert "migrated: 1, 2, 3" in capsys.readouterr().out
    assert operations.doctor(
        config_path,
        environ={},
        runner=_successful_doctor_runner,
        read_credential_resolver=lambda _: "read-credential-value",
    ) == 0
    output = capsys.readouterr().out
    assert "[pass] sqlite-schema" in output
    assert "[warn] repository-scan:1" in output
    assert "[skip] webhook-secret" in output


def test_doctor_refuses_an_incompatible_schema(tmp_path: Path, capsys) -> None:
    database = tmp_path / "events.sqlite3"
    config_path = tmp_path / "events.toml"
    _write_config(config_path, database)
    QueueStore.migrate(database, busy_timeout_ms=100)
    connection = QueueStore.open(database, busy_timeout_ms=100).connection
    connection.execute("INSERT INTO schema_migrations VALUES (?, ?)", (CURRENT_SCHEMA_VERSION + 1, "now"))
    report = _doctor_report(config_path)
    assert report.exit_code == 1
    assert report.by_code("sqlite-schema").status == "fail"


def test_doctor_reports_invalid_configuration_as_a_failed_probe(tmp_path: Path) -> None:
    config_path = tmp_path / "events.toml"
    config_path.write_text('database = "relative.sqlite3"\n', encoding="utf-8")

    report = _doctor_report(config_path)

    assert report.exit_code == 1
    assert [(probe.code, probe.status) for probe in report.probes] == [
        ("configuration", "fail")
    ]


def test_doctor_checks_sqlite_integrity_foreign_keys_wal_timeout_and_schema(
    tmp_path: Path,
) -> None:
    database = tmp_path / "events.sqlite3"
    config_path = tmp_path / "events.toml"
    _write_config(config_path, database)
    QueueStore.migrate(database, busy_timeout_ms=100)

    report = _doctor_report(config_path)

    assert {
        code: report.by_code(code).status
        for code in (
            "sqlite-open",
            "sqlite-integrity",
            "sqlite-foreign-keys",
            "sqlite-wal",
            "sqlite-busy-timeout",
            "sqlite-schema",
            "queue-status",
        )
    } == {
        "sqlite-open": "pass",
        "sqlite-integrity": "pass",
        "sqlite-foreign-keys": "pass",
        "sqlite-wal": "pass",
        "sqlite-busy-timeout": "pass",
        "sqlite-schema": "pass",
        "queue-status": "pass",
    }


@pytest.mark.parametrize(
    "damage",
    (
        "DROP TABLE project_items",
        "DROP TABLE invalidations",
        "DROP INDEX dirty_claim_idx",
    ),
)
def test_doctor_rejects_schema_shape_damage_without_mutating_the_database(
    tmp_path: Path, damage: str
) -> None:
    database = tmp_path / "events.sqlite3"
    config_path = tmp_path / "events.toml"
    _write_config(config_path, database)
    QueueStore.migrate(database, busy_timeout_ms=100)
    connection = sqlite3.connect(database)
    connection.execute(damage)
    connection.commit()
    schema_before = connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
    ).fetchall()
    connection.close()

    report = _doctor_report(config_path)

    verify = sqlite3.connect(database)
    schema_after = verify.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
    ).fetchall()
    verify.close()
    assert report.by_code("sqlite-schema").status == "fail"
    assert schema_after == schema_before


@pytest.mark.parametrize(
    ("old", "new"),
    (
        ("generation INTEGER NOT NULL", "generation TEXT NOT NULL"),
        ("generation INTEGER NOT NULL", "generation INTEGER"),
        (
            "retry_count INTEGER NOT NULL DEFAULT 0",
            "retry_count INTEGER NOT NULL DEFAULT 9",
        ),
        ("PRIMARY KEY(repository_id, target_kind, target_key),", ""),
    ),
    ids=("type", "not-null", "default", "composite-primary-key"),
)
def test_doctor_rejects_complete_dirty_target_schema_damage_with_names_preserved(
    tmp_path: Path,
    old: str,
    new: str,
) -> None:
    database = tmp_path / "events.sqlite3"
    config_path = tmp_path / "events.toml"
    _write_config(config_path, database)
    QueueStore.migrate(database, busy_timeout_ms=100)
    create_table = """
        CREATE TABLE dirty_targets (
          repository_id INTEGER NOT NULL, target_kind TEXT NOT NULL,
          target_key TEXT NOT NULL, generation INTEGER NOT NULL,
          first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
          lease_owner TEXT, lease_until TEXT,
          retry_count INTEGER NOT NULL DEFAULT 0,
          next_attempt_at TEXT, last_error TEXT,
          PRIMARY KEY(repository_id, target_kind, target_key),
          FOREIGN KEY(repository_id) REFERENCES repository_state(repository_id)
        )
    """.replace(old, new)
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("ALTER TABLE dirty_targets RENAME TO dirty_targets_old")
    connection.execute(create_table)
    connection.execute(
        "INSERT INTO dirty_targets SELECT * FROM dirty_targets_old"
    )
    connection.execute("DROP TABLE dirty_targets_old")
    connection.execute(
        "CREATE INDEX dirty_claim_idx "
        "ON dirty_targets(repository_id, lease_until, next_attempt_at)"
    )
    connection.commit()
    connection.close()

    report = _doctor_report(config_path)

    assert report.by_code("sqlite-schema").status == "fail"


def test_doctor_fails_on_a_foreign_key_violation(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    config_path = tmp_path / "events.toml"
    _write_config(config_path, database)
    QueueStore.migrate(database, busy_timeout_ms=100)
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute(
        "INSERT INTO invalidations(source_kind,source_key,repository_id,target_kind,target_key,observed_at,diagnostic_json) VALUES(?,?,?,?,?,?,?)",
        ("test", "broken", 99, "issue", "1", NOW.isoformat(), "{}"),
    )
    connection.commit()
    connection.close()

    report = _doctor_report(config_path)

    assert report.exit_code == 1
    assert report.by_code("sqlite-foreign-keys").status == "fail"


@pytest.mark.parametrize(
    ("target", "mode", "probe_code"),
    (("parent", 0o755, "database-parent"), ("file", 0o644, "database-file")),
)
def test_doctor_rejects_world_access_to_database_paths(
    tmp_path: Path, target: str, mode: int, probe_code: str
) -> None:
    database_parent = tmp_path / "state"
    database_parent.mkdir(mode=0o700)
    database = database_parent / "events.sqlite3"
    config_path = tmp_path / "events.toml"
    _write_config(config_path, database)
    QueueStore.migrate(database, busy_timeout_ms=100)
    os.chmod(database_parent if target == "parent" else database, mode)

    report = _doctor_report(config_path)

    assert report.exit_code == 1
    assert report.by_code(probe_code).status == "fail"


def test_doctor_rejects_group_shared_database_directory_without_setgid(
    tmp_path: Path,
) -> None:
    database_parent = tmp_path / "state"
    database_parent.mkdir(mode=0o770)
    database_parent.chmod(0o770)
    database = database_parent / "events.sqlite3"
    config_path = tmp_path / "events.toml"
    _write_config(config_path, database)
    QueueStore.migrate(database, busy_timeout_ms=100)
    database.chmod(0o660)

    report = _doctor_report(config_path)

    assert report.by_code("database-parent").status == "fail"


@pytest.mark.parametrize(
    ("mode", "member", "expected_status"),
    ((0o600, False, "pass"), (0o660, True, "pass"), (0o660, False, "fail")),
    ids=("owner-only", "group-member", "group-nonmember"),
)
def test_doctor_validates_existing_sqlite_sidecar_access_without_mutating_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: int,
    member: bool,
    expected_status: str,
) -> None:
    database_parent = tmp_path / "state"
    database_parent.mkdir()
    database_parent.chmod(0o2770)
    database = database_parent / "events.sqlite3"
    config_path = tmp_path / "events.toml"
    _write_config(config_path, database)
    QueueStore.migrate(database, busy_timeout_ms=100)
    store = QueueStore.open(database, busy_timeout_ms=100)
    store.register_repositories((RepositoryIdentity(1, "owner", "repo"),))
    sidecars = (Path(f"{database}-wal"), Path(f"{database}-shm"))
    for sidecar in sidecars:
        assert sidecar.exists()
        sidecar.chmod(mode)
    owner_uid = sidecars[0].stat().st_uid
    shared_gid = sidecars[0].stat().st_gid
    if mode == 0o660:
        monkeypatch.setattr(operations.os, "geteuid", lambda: owner_uid + 1)
        service_gid = shared_gid if member else shared_gid + 1
        monkeypatch.setattr(operations.os, "getegid", lambda: service_gid)
        monkeypatch.setattr(operations.os, "getgroups", lambda: [service_gid])
    before = {sidecar: stat.S_IMODE(sidecar.stat().st_mode) for sidecar in sidecars}

    try:
        report = _doctor_report(config_path)

        statuses = {probe.code: probe.status for probe in report.probes}
        assert statuses.get("database-wal") == expected_status
        assert statuses.get("database-shm") == expected_status
        assert {
            sidecar: stat.S_IMODE(sidecar.stat().st_mode) for sidecar in sidecars
        } == before
    finally:
        store.connection.close()


def test_doctor_does_not_create_absent_sqlite_sidecars(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    config_path = tmp_path / "events.toml"
    _write_config(config_path, database)
    QueueStore.migrate(database, busy_timeout_ms=100)
    store = QueueStore.open(database, busy_timeout_ms=100)
    store.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    store.connection.close()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{database}{suffix}")
        if sidecar.exists():
            sidecar.unlink()
    before = set(tmp_path.iterdir())

    _doctor_report(config_path)

    assert set(tmp_path.iterdir()) == before


def _copy_live_wal_set(
    tmp_path: Path, *, include_shm: bool
) -> tuple[Path, QueueStore]:
    origin = tmp_path / "origin.sqlite3"
    source = tmp_path / "events.sqlite3"
    QueueStore.migrate(origin, busy_timeout_ms=100)
    store = QueueStore.open(origin, busy_timeout_ms=100)
    store.register_repositories((RepositoryIdentity(1, "owner", "repo"),))
    shutil.copy2(origin, source)
    shutil.copy2(Path(f"{origin}-wal"), Path(f"{source}-wal"))
    if include_shm:
        shutil.copy2(Path(f"{origin}-shm"), Path(f"{source}-shm"))
    return source, store


def test_doctor_does_not_create_shm_for_a_valid_wal_only_source(
    tmp_path: Path,
) -> None:
    database, origin_store = _copy_live_wal_set(tmp_path, include_shm=False)
    config_path = tmp_path / "events.toml"
    _write_config(config_path, database)
    source_shm = Path(f"{database}-shm")
    assert not source_shm.exists()

    try:
        report = _doctor_report(config_path)

        assert report.by_code("sqlite-schema").status == "pass"
        assert not source_shm.exists()
    finally:
        origin_store.connection.close()


def test_doctor_does_not_mutate_an_existing_sqlite_source_set(
    tmp_path: Path,
) -> None:
    database, origin_store = _copy_live_wal_set(tmp_path, include_shm=True)
    config_path = tmp_path / "events.toml"
    _write_config(config_path, database)
    source_paths = (database, Path(f"{database}-wal"), Path(f"{database}-shm"))
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns) for path in source_paths
    }

    try:
        report = _doctor_report(config_path)

        assert report.by_code("sqlite-schema").status == "pass"
        assert {
            path: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in source_paths
        } == before
    finally:
        origin_store.connection.close()


def test_doctor_accepts_database_paths_shared_with_the_current_restricted_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_parent = tmp_path / "state"
    database_parent.mkdir()
    database_parent.chmod(0o2770)
    database = database_parent / "events.sqlite3"
    config_path = tmp_path / "events.toml"
    _write_config(config_path, database)
    QueueStore.migrate(database, busy_timeout_ms=100)
    database.chmod(0o660)
    service_gid = database.stat().st_gid
    owner_uid = database.stat().st_uid
    monkeypatch.setattr(operations.os, "geteuid", lambda: owner_uid + 1)
    monkeypatch.setattr(operations.os, "getegid", lambda: service_gid)
    monkeypatch.setattr(operations.os, "getgroups", lambda: [service_gid])

    report = _doctor_report(config_path)

    assert report.by_code("database-parent").status == "pass"
    assert report.by_code("database-file").status == "pass"


def test_doctor_rejects_a_database_group_unavailable_to_the_current_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_parent = tmp_path / "state"
    database_parent.mkdir()
    database_parent.chmod(0o2770)
    database = database_parent / "events.sqlite3"
    config_path = tmp_path / "events.toml"
    _write_config(config_path, database)
    QueueStore.migrate(database, busy_timeout_ms=100)
    database.chmod(0o660)
    owner_uid = database.stat().st_uid
    service_gid = database.stat().st_gid + 1
    monkeypatch.setattr(operations.os, "geteuid", lambda: owner_uid + 1)
    monkeypatch.setattr(operations.os, "getegid", lambda: service_gid)
    monkeypatch.setattr(operations.os, "getgroups", lambda: [service_gid])

    report = _doctor_report(config_path)

    assert report.by_code("database-parent").status == "fail"
    assert report.by_code("database-file").status == "fail"


def test_doctor_detects_repository_id_mismatch_without_github_writes(
    tmp_path: Path,
) -> None:
    database = tmp_path / "events.sqlite3"
    config_path = tmp_path / "events.toml"
    _write_config(config_path, database)
    QueueStore.migrate(database, busy_timeout_ms=100)
    commands: list[list[str]] = []

    def runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[:3] == ["gh", "api", "repos/owner/repo"]:
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"id": 2, "full_name": "owner/repo"}), ""
            )
        return _successful_doctor_runner(command, **kwargs)

    report = _doctor_report(config_path, runner=runner)

    assert report.by_code("repository-read:owner/repo").status == "pass"
    assert report.by_code("repository-identity:owner/repo").status == "fail"
    assert commands == [
        ["gh", "api", "repos/owner/repo"],
        ["gh", "api", "repos/owner/repo/commits?per_page=1"],
        ["gh", "api", f"repos/owner/repo/commits/{'a' * 40}/check-runs"],
        ["gh", "api", f"repos/owner/repo/commits/{'a' * 40}/status"],
        [
            "gh",
            "project",
            "field-list",
            "1",
            "--owner",
            "owner",
            "--limit",
            "1000",
            "--format",
            "json",
        ],
    ]


def test_doctor_exercises_check_run_and_combined_status_reads_at_a_discovered_sha(
    tmp_path: Path,
) -> None:
    database = tmp_path / "events.sqlite3"
    config_path = tmp_path / "events.toml"
    _write_config(config_path, database)
    QueueStore.migrate(database, busy_timeout_ms=100)
    commands: list[list[str]] = []

    def runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return _successful_doctor_runner(command, **kwargs)

    report = _doctor_report(config_path, runner=runner)

    statuses = {probe.code: probe.status for probe in report.probes}
    assert statuses.get("checks-read:owner/repo") == "pass"
    assert statuses.get("statuses-read:owner/repo") == "pass"
    assert [command for command in commands if command[:2] == ["gh", "api"]] == [
        ["gh", "api", "repos/owner/repo"],
        ["gh", "api", "repos/owner/repo/commits?per_page=1"],
        ["gh", "api", f"repos/owner/repo/commits/{'a' * 40}/check-runs"],
        ["gh", "api", f"repos/owner/repo/commits/{'a' * 40}/status"],
    ]


def test_doctor_skips_check_and_status_capabilities_for_an_empty_repository(
    tmp_path: Path,
) -> None:
    database = tmp_path / "events.sqlite3"
    config_path = tmp_path / "events.toml"
    _write_config(config_path, database)
    QueueStore.migrate(database, busy_timeout_ms=100)

    def runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if command[:3] == ["gh", "api", "repos/owner/repo/commits?per_page=1"]:
            return subprocess.CompletedProcess(command, 0, "[]", "")
        return _successful_doctor_runner(command, **kwargs)

    report = _doctor_report(config_path, runner=runner)

    statuses = {probe.code: probe.status for probe in report.probes}
    assert statuses.get("checks-read:owner/repo") == "skip"
    assert statuses.get("statuses-read:owner/repo") == "skip"


def test_doctor_fails_denied_check_and_status_capability_reads(
    tmp_path: Path,
) -> None:
    database = tmp_path / "events.sqlite3"
    config_path = tmp_path / "events.toml"
    _write_config(config_path, database)
    QueueStore.migrate(database, busy_timeout_ms=100)

    def runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        endpoint = command[2] if command[:2] == ["gh", "api"] else ""
        if endpoint.endswith("/check-runs") or endpoint.endswith("/status"):
            return subprocess.CompletedProcess(command, 1, "", "private denial")
        return _successful_doctor_runner(command, **kwargs)

    report = _doctor_report(config_path, runner=runner)

    statuses = {probe.code: probe.status for probe in report.probes}
    assert statuses.get("checks-read:owner/repo") == "fail"
    assert statuses.get("statuses-read:owner/repo") == "fail"
    assert "private denial" not in "\n".join(
        f"{probe.message} {probe.remedy}" for probe in report.probes
    )


def test_doctor_skips_field_absence_when_the_board_field_list_is_incomplete(
    tmp_path: Path,
) -> None:
    database = tmp_path / "events.sqlite3"
    config_path = tmp_path / "events.toml"
    _write_config(config_path, database)
    QueueStore.migrate(database, busy_timeout_ms=100)

    def runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if command[:3] == ["gh", "project", "field-list"]:
            fields = [{"name": "Status"}] + [
                {"name": f"Field {number}"} for number in range(2, 31)
            ]
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps({"fields": fields, "totalCount": 31}),
                "",
            )
        return _successful_doctor_runner(command, **kwargs)

    report = _doctor_report(config_path, runner=runner)

    assert report.by_code("board-read:owner/1").status == "pass"
    assert report.by_code("board-fields:owner/1").status == "skip"


def test_doctor_reports_inaccessible_board_and_all_four_probe_statuses(
    tmp_path: Path,
) -> None:
    database = tmp_path / "events.sqlite3"
    config_path = tmp_path / "events.toml"
    _write_config(config_path, database)
    QueueStore.migrate(database, busy_timeout_ms=100)

    def runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if command[:3] == ["gh", "project", "field-list"]:
            return subprocess.CompletedProcess(command, 1, "", "sensitive-api-detail")
        return _successful_doctor_runner(command, **kwargs)

    report = _doctor_report(config_path, runner=runner)

    assert report.by_code("board-read:owner/1").status == "fail"
    assert report.by_code("board-fields:owner/1").status == "skip"
    assert report.by_code("repository-scan:1").status == "warn"
    assert report.by_code("configuration").status == "pass"
    assert {probe.status for probe in report.probes} == {"pass", "fail", "warn", "skip"}
    assert "sensitive-api-detail" not in "\n".join(
        f"{probe.message} {probe.remedy}" for probe in report.probes
    )


@pytest.mark.parametrize(
    ("content", "mode", "expected_status"),
    ((b"private-value\n", 0o600, "pass"), (b"private-value", 0o640, "fail"), (b"\n", 0o600, "fail")),
)
def test_doctor_checks_webhook_secret_without_disclosing_it(
    tmp_path: Path,
    capsys,
    content: bytes,
    mode: int,
    expected_status: str,
) -> None:
    database = tmp_path / "events.sqlite3"
    config_path = tmp_path / "events.toml"
    secret_path = tmp_path / "webhook-secret"
    _write_config(config_path, database)
    QueueStore.migrate(database, busy_timeout_ms=100)
    secret_path.write_bytes(content)
    os.chmod(secret_path, mode)

    assert operations.doctor(
        config_path,
        environ={"AGENT_SESSION_WEBHOOK_SECRET_FILE": str(secret_path)},
        runner=_successful_doctor_runner,
        read_credential_resolver=lambda _: "read-credential-value",
    ) == (0 if expected_status == "pass" else 1)
    output = capsys.readouterr().out

    assert f"[{expected_status}] webhook-secret" in output
    assert "private-value" not in output


def test_doctor_reports_malformed_stored_clocks_and_continues_independent_probes(
    tmp_path: Path, capsys
) -> None:
    database = tmp_path / "events.sqlite3"
    config_path = tmp_path / "events.toml"
    _write_config(config_path, database)
    QueueStore.migrate(database, busy_timeout_ms=100)
    store = QueueStore.open(database, busy_timeout_ms=100)
    store.register_repositories((RepositoryIdentity(1, "owner", "repo"),))
    store.connection.execute(
        "UPDATE repository_state SET last_hint_at=? WHERE repository_id=1",
        ("private-malformed-clock",),
    )

    assert operations.doctor(
        config_path,
        environ={},
        runner=_successful_doctor_runner,
        read_credential_resolver=lambda _: "read-credential-value",
    ) == 1
    output = capsys.readouterr().out

    assert "[fail] queue-status" in output
    assert "[pass] repository-read:owner/repo" in output
    assert "private-malformed-clock" not in output


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
    assert payload["latest_delivery_age_seconds"] is None


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
    assert payload["latest_delivery_age_seconds"] is None
    assert payload["repositories"] == [{
        "repository_id": 1,
        "last_hint_at": "2026-08-25T00:00:00+00:00",
        "last_hint_age_seconds": 0,
        "last_scan_started_at": "2026-08-25T00:00:00+00:00",
        "last_scan_started_age_seconds": 0,
        "last_scan_success_at": "2026-08-24T23:59:00+00:00",
        "last_scan_success_age_seconds": 60,
        "scan_lease_owner": "scan",
        "scan_lease_until": "2026-08-25T00:01:00+00:00",
        "last_error": "",
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
[polling]
projects_interval_seconds = 60
reactions_interval_seconds = 60
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
    assert "migrated: 1, 2, 3" in capsys.readouterr().out


def test_cli_doctor_reports_invalid_configuration_without_a_traceback(
    tmp_path: Path, capsys
) -> None:
    from agent_sessions.events.cli import main

    config_path = tmp_path / "events.toml"
    config_path.write_text('database = "relative.sqlite3"\n', encoding="utf-8")

    assert main(["doctor", "--config", str(config_path)]) == 1
    assert "[fail] configuration" in capsys.readouterr().out


def test_cli_other_commands_treat_invalid_configuration_as_usage_error(
    tmp_path: Path,
) -> None:
    from agent_sessions.events.cli import main

    config_path = tmp_path / "events.toml"
    config_path.write_text('database = "relative.sqlite3"\n', encoding="utf-8")

    with pytest.raises(SystemExit) as exited:
        main(["migrate", "--config", str(config_path)])

    assert exited.value.code == 2


@pytest.mark.parametrize(
    ("option", "value"),
    (
        ("--deliveries-days", "0"),
        ("--deliveries-days", "-1"),
        ("--invalidations-days", "0"),
        ("--invalidations-days", "-1"),
    ),
)
def test_cli_rejects_non_positive_prune_retention_without_pruning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    option: str,
    value: str,
) -> None:
    from agent_sessions.events.cli import main

    database = tmp_path / "events.sqlite3"
    config_path = tmp_path / "events.toml"
    _write_config(config_path, database)
    prune_calls: list[object] = []
    def record_prune(*args: object, **kwargs: object) -> int:
        prune_calls.append((args, kwargs))
        return 0

    monkeypatch.setattr(operations, "prune", record_prune)

    with pytest.raises(SystemExit) as exited:
        main(["prune", "--config", str(config_path), option, value])

    assert exited.value.code == 2
    assert prune_calls == []


@pytest.mark.parametrize("field", ("database", "repositories", "boards"))
def test_cli_handles_wrong_configuration_types_without_a_traceback_or_disclosure(
    tmp_path: Path, capsys, monkeypatch, field: str
) -> None:
    from agent_sessions.events.cli import main

    database = tmp_path / "events.sqlite3"
    config_path = tmp_path / "events.toml"
    _write_config(config_path, database)
    text = config_path.read_text(encoding="utf-8")
    if field == "database":
        text = text.replace(f'database = "{database}"', "database = 42")
    elif field == "repositories":
        start = text.index("[[repositories]]")
        end = text.index("[[boards]]")
        text = text[:start] + text[end:]
        text = text.replace("[scan]", "repositories = {}\n[scan]")
    else:
        text = text[: text.index("[[boards]]")]
        text = text.replace("[scan]", "boards = {}\n[scan]")
    config_path.write_text(text, encoding="utf-8")
    marker = "private-credential-content"
    monkeypatch.setenv("AGENT_GH_READ_TOKEN", marker)

    assert main(["doctor", "--config", str(config_path)]) == 1
    with pytest.raises(SystemExit) as exited:
        main(["migrate", "--config", str(config_path)])

    captured = capsys.readouterr()
    assert exited.value.code == 2
    assert "[fail] configuration" in captured.out
    assert marker not in captured.out + captured.err


@pytest.mark.parametrize(
    "arguments",
    [
        ["--help"],
        ["serve", "--help"],
        ["poll-projects", "--help"],
        ["poll-reactions", "--help"],
        ["doctor", "--help"],
        ["queue-status", "--help"],
        ["migrate", "--help"],
        ["prune", "--help"],
    ],
)
def test_cli_help_surfaces_exit_successfully(arguments: list[str], capsys) -> None:
    from agent_sessions.events.cli import main

    with pytest.raises(SystemExit) as exited:
        main(arguments)

    assert exited.value.code == 0
    assert "usage:" in capsys.readouterr().out


def test_cli_top_level_help_exposes_only_the_supported_commands(capsys) -> None:
    from agent_sessions.events.cli import main

    with pytest.raises(SystemExit):
        main(["--help"])
    help_text = capsys.readouterr().out

    command_group = re.search(r"\{([^}]+)\}", help_text)
    assert command_group is not None
    assert set(command_group.group(1).split(",")) == {
        "serve",
        "poll-projects",
        "poll-reactions",
        "doctor",
        "queue-status",
        "migrate",
        "prune",
    }
