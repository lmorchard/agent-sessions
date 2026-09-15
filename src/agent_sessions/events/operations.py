"""Read-only diagnostics and local queue maintenance commands."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import stat
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from agent_sessions.driver import credentials

from . import config
from .github import ProjectFieldsIncomplete, fetch_project_fields
from .models import EventsConfig, QueueStatus
from .store import CURRENT_SCHEMA_VERSION, QueueStore, schema_shape_is_current

ProbeStatus = Literal["pass", "fail", "warn", "skip"]
CredentialResolver = Callable[[Mapping[str, str]], str]
CommandRunner = Callable[..., Any]

@dataclass(frozen=True)
class DoctorProbe:
    """One independently actionable diagnostic result."""

    code: str
    status: ProbeStatus
    message: str
    remedy: str = ""


@dataclass(frozen=True)
class DoctorReport:
    """Structured doctor output for CLI rendering and behavioral tests."""

    probes: tuple[DoctorProbe, ...]

    @property
    def exit_code(self) -> int:
        return 1 if any(probe.status == "fail" for probe in self.probes) else 0

    def by_code(self, code: str) -> DoctorProbe:
        return next(probe for probe in self.probes if probe.code == code)


def _timestamp(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _age_seconds(value: datetime | None, now: datetime) -> int | None:
    return None if value is None else max(0, int((now - value).total_seconds()))


def migrate(database: Path, *, busy_timeout_ms: int) -> int:
    versions = QueueStore.migrate(database, busy_timeout_ms=busy_timeout_ms)
    print("migrated: " + (", ".join(map(str, versions)) if versions else "already current"))
    return 0


def _path_details(
    path: Path, *, code: str, kind: Literal["directory", "file"]
) -> tuple[os.stat_result | None, DoctorProbe | None]:
    try:
        details = path.stat()
    except OSError:
        return None, DoctorProbe(
            code, "fail", f"{kind} is unavailable", f"create and restrict {path}"
        )
    expected_type = stat.S_ISDIR if kind == "directory" else stat.S_ISREG
    if not expected_type(details.st_mode):
        return None, DoctorProbe(
            code,
            "fail",
            f"path is not a regular {kind}",
            f"replace {path} with a {kind}",
        )
    return details, None


def _owner_only_path_probe(
    path: Path, *, code: str, kind: Literal["directory", "file"]
) -> DoctorProbe:
    details, error = _path_details(path, code=code, kind=kind)
    if error is not None:
        return error
    assert details is not None
    if details.st_uid != os.geteuid():
        return DoctorProbe(
            code,
            "fail",
            f"{kind} has the wrong owner",
            f"make the service account own {path}",
        )
    if details.st_mode & 0o077:
        mode = "0700" if kind == "directory" else "0600"
        return DoctorProbe(
            code,
            "fail",
            f"{kind} permits group or other access",
            f"set mode {mode} on {path}",
        )
    return DoctorProbe(code, "pass", f"{kind} is owner-only")


def _database_path_probe(
    path: Path, *, code: str, kind: Literal["directory", "file"]
) -> DoctorProbe:
    details, error = _path_details(path, code=code, kind=kind)
    if error is not None:
        return error
    assert details is not None
    mode = stat.S_IMODE(details.st_mode)
    if mode & 0o007:
        return DoctorProbe(
            code,
            "fail",
            f"database {kind} permits world access",
            f"remove all world permissions from {path}",
        )
    required_owner = 0o700 if kind == "directory" else 0o600
    required_group = 0o070 if kind == "directory" else 0o060
    group_mode = mode & 0o070
    if group_mode not in {0, required_group}:
        expected = "2770" if kind == "directory" else "0660"
        return DoctorProbe(
            code,
            "fail",
            f"database {kind} has incomplete group permissions",
            f"set mode {expected} for shared database access",
        )
    if kind == "directory" and group_mode == required_group and not mode & stat.S_ISGID:
        return DoctorProbe(
            code,
            "fail",
            "shared database directory does not inherit its group",
            f"set mode 2770 on {path}",
        )
    owner_access = (
        details.st_uid == os.geteuid()
        and mode & required_owner == required_owner
    )
    process_groups = {os.getegid(), *os.getgroups()}
    group_access = (
        details.st_gid in process_groups and group_mode == required_group
    )
    if group_access:
        return DoctorProbe(
            code, "pass", f"database {kind} is available through a restricted group"
        )
    if owner_access and group_mode == 0:
        return DoctorProbe(code, "pass", f"database {kind} is owner-only")
    if owner_access:
        return DoctorProbe(
            code,
            "warn",
            f"database {kind} owner can access it but the shared group is inactive",
            "run doctor with the service's database supplementary group",
        )
    return DoctorProbe(
        code,
        "fail",
        f"database {kind} is unavailable to this service identity",
        "add the service to the database group and verify group ownership",
    )


def _query_one(connection: sqlite3.Connection, statement: str) -> Any:
    row = connection.execute(statement).fetchone()
    return None if row is None else row[0]


def _copy_queue_snapshot(database: Path, wal_files: list[Path], target: Path) -> None:
    """Copy the database and its WAL into `target`. Never the `-shm`.

    The `-shm` is the wal-index: a derived cache, not data. SQLite rebuilds it for the
    copy, so copying it buys nothing and omitting it removes a file that can disagree
    with the WAL beside it.

    **It is not, measured, a source of false corruption, and the review that prompted
    this said otherwise.** A copied index cannot make a healthy database look damaged: the
    wal-index header carries salts and a checksum that must match the WAL, and SQLite
    rebuilds it when they do not. Verified by copying a database with a deliberately
    corrupted `-shm` -- `integrity_check` returned `ok` and the schema was intact. So this
    omission is hygiene, not the fix; the two changes below are the fix.

    The WAL is copied best effort. A checkpoint can remove it between the `stat` that
    found it and this copy, and in WAL mode the main file is always a valid database on
    its own, so a vanished WAL is a *staler* snapshot rather than a failure. Previously
    that race raised `FileNotFoundError` and dropped every database probe behind one hard
    `sqlite-open` failure.

    Nothing here opens the source, and that is a constraint rather than an oversight.
    `VACUUM INTO` and `Connection.backup()` would give a genuinely atomic snapshot; both
    were measured and both disqualify themselves, because each has to open the source and
    a read-only open of a live WAL database rewrites the `-shm` read-marks -- and creates
    a `-shm` where none existed. `test_doctor_does_not_mutate_an_existing_sqlite_source_set`
    and `test_doctor_does_not_create_shm_for_a_valid_wal_only_source` forbid exactly that.
    """
    shutil.copy2(database, target / database.name)
    for wal in wal_files:
        try:
            shutil.copy2(wal, target / wal.name)
        except FileNotFoundError:
            continue


def _fresh_snapshot_integrity(database: Path, wal_files: list[Path]) -> bool:
    """Take a second snapshot and re-run `integrity_check`. True only if it passes.

    An unlocked copy can catch a checkpoint mid-flight, yielding a main file and a WAL
    from either side of it. That is a *transient* inconsistency in the copy rather than
    damage in the source, and one sample cannot tell them apart. So a first failure is
    retried once from a fresh snapshot, and damage is reported only when it reproduces --
    which is what damage does.

    Stated honestly: this window was **not** reproduced. It is narrow and timing
    dependent, and the cost of covering it is one extra copy on a path that has already
    decided to report the most alarming result doctor can produce. Real damage still
    fails, because it fails twice; `test_doctor_reports_real_damage_after_the_retry`
    holds that end down.
    """
    with tempfile.TemporaryDirectory(prefix="agent-session-doctor-retry-") as retry_dir:
        target = Path(retry_dir)
        try:
            _copy_queue_snapshot(database, wal_files, target)
            connection = sqlite3.connect(
                f"{(target / database.name).as_uri()}?mode=ro", isolation_level=None, uri=True
            )
        except (OSError, sqlite3.Error):
            return False
        try:
            return [row[0] for row in connection.execute("PRAGMA integrity_check")] == ["ok"]
        except sqlite3.Error:
            return False
        finally:
            connection.close()


def _sqlite_probes(loaded: EventsConfig) -> tuple[list[DoctorProbe], QueueStatus | None]:
    probes = [
        _database_path_probe(
            loaded.database.parent, code="database-parent", kind="directory"
        ),
        _database_path_probe(loaded.database, code="database-file", kind="file"),
    ]
    # Both sidecars are *reported* on; only the WAL is ever copied. See
    # `_copy_queue_snapshot` for why the `-shm` is deliberately excluded.
    wal_files: list[Path] = []
    for suffix, code in (("-wal", "database-wal"), ("-shm", "database-shm")):
        sidecar = Path(f"{loaded.database}{suffix}")
        try:
            sidecar.stat()
        except FileNotFoundError:
            continue
        except OSError:
            probes.append(
                _database_path_probe(sidecar, code=code, kind="file")
            )
        else:
            if suffix == "-wal":
                wal_files.append(sidecar)
            probes.append(
                _database_path_probe(sidecar, code=code, kind="file")
            )
    snapshot = tempfile.TemporaryDirectory(prefix="agent-session-doctor-")
    snapshot_database = Path(snapshot.name) / loaded.database.name
    try:
        _copy_queue_snapshot(loaded.database, wal_files, Path(snapshot.name))
    except OSError:
        snapshot.cleanup()
        probes.append(
            DoctorProbe(
                "sqlite-open",
                "fail",
                "database could not be copied for a read-only probe",
                "verify database access and retry doctor",
            )
        )
        return probes, None
    try:
        connection = sqlite3.connect(
            f"{snapshot_database.as_uri()}?mode=ro",
            isolation_level=None,
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {loaded.busy_timeout_ms}")
    except sqlite3.Error:
        snapshot.cleanup()
        probes.append(
            DoctorProbe(
                "sqlite-open",
                "fail",
                "database could not be opened read-only",
                "stop queue services, verify the path, then run migrate",
            )
        )
        return probes, None

    probes.append(DoctorProbe("sqlite-open", "pass", "database opened read-only"))
    status: QueueStatus | None = None
    try:
        try:
            integrity = [
                row[0] for row in connection.execute("PRAGMA integrity_check")
            ]
            ready = integrity == ["ok"] or _fresh_snapshot_integrity(
                loaded.database, wal_files
            )
            probes.append(
                DoctorProbe(
                    "sqlite-integrity",
                    "pass" if ready else "fail",
                    "integrity check passed"
                    if ready
                    else "integrity check found damage",
                    "restore a verified backup; doctor never repairs corruption"
                    if not ready
                    else "",
                )
            )
        except sqlite3.Error:
            probes.append(
                DoctorProbe(
                    "sqlite-integrity",
                    "fail",
                    "integrity check could not complete",
                    "restore a verified backup; doctor never repairs corruption",
                )
            )

        try:
            foreign_keys_enabled = (
                _query_one(connection, "PRAGMA foreign_keys") == 1
            )
            violations = list(connection.execute("PRAGMA foreign_key_check"))
            ready = foreign_keys_enabled and not violations
            probes.append(
                DoctorProbe(
                    "sqlite-foreign-keys",
                    "pass" if ready else "fail",
                    "foreign keys are enabled and valid"
                    if ready
                    else "foreign-key enforcement or stored references are invalid",
                    "restore a consistent backup before restarting services"
                    if not ready
                    else "",
                )
            )
        except sqlite3.Error:
            probes.append(
                DoctorProbe(
                    "sqlite-foreign-keys",
                    "fail",
                    "foreign-key check could not complete",
                    "inspect the database offline before restarting services",
                )
            )

        try:
            journal_mode = str(
                _query_one(connection, "PRAGMA journal_mode") or ""
            ).lower()
            ready = journal_mode == "wal"
            probes.append(
                DoctorProbe(
                    "sqlite-wal",
                    "pass" if ready else "fail",
                    "WAL mode is active" if ready else "WAL mode is inactive",
                    "stop services and run migrate to initialize the database"
                    if not ready
                    else "",
                )
            )
        except sqlite3.Error:
            probes.append(
                DoctorProbe(
                    "sqlite-wal",
                    "fail",
                    "journal mode could not be read",
                    "inspect the database offline before restarting services",
                )
            )

        try:
            busy_timeout = int(
                _query_one(connection, "PRAGMA busy_timeout") or 0
            )
            ready = busy_timeout == loaded.busy_timeout_ms
            probes.append(
                DoctorProbe(
                    "sqlite-busy-timeout",
                    "pass" if ready else "fail",
                    "busy timeout matches configuration"
                    if ready
                    else "busy timeout differs from configuration",
                    "restart the command with the shared events configuration"
                    if not ready
                    else "",
                )
            )
        except (sqlite3.Error, ValueError, TypeError):
            probes.append(
                DoctorProbe(
                    "sqlite-busy-timeout",
                    "fail",
                    "busy timeout could not be read",
                    "inspect the database connection settings",
                )
            )

        schema_ready = False
        try:
            versions = [
                row[0]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            ]
            schema_ready = versions == list(
                range(1, CURRENT_SCHEMA_VERSION + 1)
            ) and schema_shape_is_current(connection)
            probes.append(
                DoctorProbe(
                    "sqlite-schema",
                    "pass" if schema_ready else "fail",
                    f"schema version {CURRENT_SCHEMA_VERSION} is compatible"
                    if schema_ready
                    else "schema version is incompatible",
                    "stop all queue services and run migrate"
                    if not schema_ready
                    else "",
                )
            )
        except sqlite3.Error:
            probes.append(
                DoctorProbe(
                    "sqlite-schema",
                    "fail",
                    "schema metadata is unreadable",
                    "stop all queue services and run migrate",
                )
            )

        if schema_ready:
            try:
                status = QueueStore(connection).status(
                    now=datetime.now().astimezone()
                )
                probes.append(
                    DoctorProbe(
                        "queue-status",
                        "pass",
                        "queue clocks and leases are readable",
                    )
                )
            except (sqlite3.Error, ValueError, TypeError, AttributeError):
                probes.append(
                    DoctorProbe(
                        "queue-status",
                        "fail",
                        "queue clocks or leases are unreadable",
                        "inspect the database offline before restarting services",
                    )
                )
    finally:
        connection.close()
        snapshot.cleanup()
    return probes, status


def _success_clock_probes(
    loaded: EventsConfig, status: QueueStatus
) -> list[DoctorProbe]:
    probes: list[DoctorProbe] = []
    if status.latest_delivery_at is None:
        probes.append(
            DoctorProbe(
                "webhook-delivery-clock",
                "warn",
                "no verified webhook delivery has been recorded",
                "send a signed test delivery after the receiver starts",
            )
        )
    else:
        probes.append(
            DoctorProbe(
                "webhook-delivery-clock",
                "pass",
                "a verified webhook delivery is recorded",
            )
        )

    repositories = {item.repository_id: item for item in status.repositories}
    pollers_by_key = {item.source_key: item for item in status.pollers}
    for repository in loaded.repositories:
        repository_id = repository.identity.id
        repository_status = repositories.get(repository_id)
        scan_success = (
            None
            if repository_status is None
            else repository_status.last_scan_success_at
        )
        probes.append(
            DoctorProbe(
                f"repository-scan:{repository_id}",
                "pass" if scan_success is not None else "warn",
                "a successful full scan is recorded"
                if scan_success is not None
                else "no successful full scan is recorded",
                "run the repository driver once and inspect queue-status"
                if scan_success is None
                else "",
            )
        )
        reaction_key = f"reactions:{repository_id}"
        reaction = pollers_by_key.get(reaction_key)
        reaction_success = None if reaction is None else reaction.last_success_at
        probes.append(
            DoctorProbe(
                f"poller-success:{reaction_key}",
                "pass" if reaction_success is not None else "warn",
                "a successful reaction poll is recorded"
                if reaction_success is not None
                else "no successful reaction poll is recorded",
                "run poll-reactions once and inspect queue-status"
                if reaction_success is None
                else "",
            )
        )
    for board in loaded.boards:
        source_key = f"projects:{board.key}"
        poller = pollers_by_key.get(source_key)
        poll_success = None if poller is None else poller.last_success_at
        probes.append(
            DoctorProbe(
                f"poller-success:{source_key}",
                "pass" if poll_success is not None else "warn",
                "a successful Projects poll is recorded"
                if poll_success is not None
                else "no successful Projects poll is recorded",
                "run poll-projects once and inspect queue-status"
                if poll_success is None
                else "",
            )
        )
    return probes


#: The credential is *configured* when either the value or its `_CMD` indirection is
#: present. Used to tell "nothing to resolve" from "resolution broke", which is the
#: difference between a skip and a failure.
_READ_CREDENTIAL_VARS = (
    credentials.READ_TOKEN_VAR,
    credentials.READ_TOKEN_VAR + credentials.CMD_SUFFIX,
)


def _resolve_credential(
    code: str,
    environ: Mapping[str, str],
    resolver: CredentialResolver,
    *,
    remedy: str,
) -> tuple[str, DoctorProbe]:
    """Resolve the read credential, distinguishing absent configuration from a break.

    Every resolver failure used to become `status="skip"`, and `DoctorReport.exit_code`
    only fails on `fail`. So a broken credential helper -- an unreadable key file, a
    keychain that refuses, a `_CMD` that exits non-zero -- made every repository, board,
    check-run and status probe report `skip`, nothing report `fail`, and
    `agent-session-events doctor` exit **0** while the service could not authenticate at
    all. A pre-startup check that passes when authentication is impossible is worse than
    no check.

    Absent configuration is still a skip: there is nothing to resolve and nothing broken.
    Configured-but-unresolvable is a failure, and the exception type is named so the
    operator can tell a missing file from a refused keychain. The type is all that is
    reported -- a resolver failure can carry the secret in its message.
    """
    configured = any((environ.get(var) or "").strip() for var in _READ_CREDENTIAL_VARS)
    try:
        token = resolver(environ).strip()
    except Exception as error:  # noqa: BLE001 -- doctor reports, it does not crash
        if configured:
            return "", DoctorProbe(
                code,
                "fail",
                f"credential is configured but could not be resolved ({type(error).__name__})",
                remedy,
            )
        token = ""
    if not token:
        if configured:
            return "", DoctorProbe(
                code,
                "fail",
                "credential is configured but resolved to an empty value",
                remedy,
            )
        return "", DoctorProbe(code, "skip", "credential is not configured", remedy)
    return token, DoctorProbe(
        code, "pass", "credential resolved without disclosure"
    )


def _github_json(
    command: list[str],
    *,
    token: str,
    environ: Mapping[str, str],
    runner: CommandRunner,
) -> object:
    child_env = dict(environ)
    child_env["GH_TOKEN"] = token
    child_env["GITHUB_TOKEN"] = token
    try:
        result = runner(command, capture_output=True, text=True, env=child_env)
    except OSError as error:
        raise RuntimeError(type(error).__name__) from None
    if result.returncode != 0:
        raise RuntimeError(f"exit {result.returncode}")
    try:
        return cast(object, json.loads(result.stdout))
    except (TypeError, json.JSONDecodeError):
        raise RuntimeError("malformed JSON") from None


def _repository_probes(
    loaded: EventsConfig,
    *,
    token: str,
    environ: Mapping[str, str],
    runner: CommandRunner,
) -> list[DoctorProbe]:
    probes: list[DoctorProbe] = []
    for repository in loaded.repositories:
        identity = repository.identity
        label = f"{identity.owner}/{identity.name}"
        try:
            response = _github_json(
                ["gh", "api", f"repos/{label}"],
                token=token,
                environ=environ,
                runner=runner,
            )
        except RuntimeError:
            probes.extend(
                (
                    DoctorProbe(
                        f"repository-read:{label}",
                        "fail",
                        "installation read credential cannot read the repository",
                        "grant the App repository read access and retry doctor",
                    ),
                    DoctorProbe(
                        f"repository-identity:{label}",
                        "skip",
                        "repository identity could not be verified",
                        "restore repository read access and retry doctor",
                    ),
                    DoctorProbe(
                        f"checks-read:{label}",
                        "skip",
                        "check-run capability was not exercised",
                        "restore repository read access and retry doctor",
                    ),
                    DoctorProbe(
                        f"statuses-read:{label}",
                        "skip",
                        "combined-status capability was not exercised",
                        "restore repository read access and retry doctor",
                    ),
                )
            )
            continue
        probes.append(
            DoctorProbe(
                f"repository-read:{label}", "pass", "repository is readable"
            )
        )
        actual_id = response.get("id") if isinstance(response, dict) else None
        actual_name = (
            response.get("full_name") if isinstance(response, dict) else None
        )
        matches = (
            actual_id == identity.id
            and isinstance(actual_name, str)
            and actual_name.casefold() == label.casefold()
        )
        probes.append(
            DoctorProbe(
                f"repository-identity:{label}",
                "pass" if matches else "fail",
                "numeric ID and owner/name match configuration"
                if matches
                else "numeric ID or owner/name differs from configuration",
                "replace the configured repository identity with the GET response"
                if not matches
                else "",
            )
        )
        try:
            commits = _github_json(
                ["gh", "api", f"repos/{label}/commits?per_page=1"],
                token=token,
                environ=environ,
                runner=runner,
            )
        except RuntimeError:
            commits = None
        if commits == []:
            probes.extend(
                (
                    DoctorProbe(
                        f"checks-read:{label}",
                        "skip",
                        "repository has no commit for a check-run read probe",
                    ),
                    DoctorProbe(
                        f"statuses-read:{label}",
                        "skip",
                        "repository has no commit for a combined-status read probe",
                    ),
                )
            )
            continue
        sha = (
            commits[0].get("sha")
            if isinstance(commits, list)
            and commits
            and isinstance(commits[0], dict)
            else None
        )
        if not (
            isinstance(sha, str)
            and len(sha) == 40
            and all(character in "0123456789abcdefABCDEF" for character in sha)
        ):
            probes.extend(
                (
                    DoctorProbe(
                        f"checks-read:{label}",
                        "fail",
                        "a commit could not be discovered for the check-run probe",
                        "verify repository contents access and retry doctor",
                    ),
                    DoctorProbe(
                        f"statuses-read:{label}",
                        "fail",
                        "a commit could not be discovered for the combined-status probe",
                        "verify repository contents access and retry doctor",
                    ),
                )
            )
            continue
        capability_reads = (
            (
                "checks-read",
                "check-runs",
                "check_runs",
                "check-run",
            ),
            (
                "statuses-read",
                "status",
                "statuses",
                "combined-status",
            ),
        )
        for code, endpoint, response_field, label_name in capability_reads:
            try:
                capability = _github_json(
                    ["gh", "api", f"repos/{label}/commits/{sha}/{endpoint}"],
                    token=token,
                    environ=environ,
                    runner=runner,
                )
                ready = (
                    isinstance(capability, dict)
                    and isinstance(capability.get(response_field), list)
                )
            except RuntimeError:
                ready = False
            probes.append(
                DoctorProbe(
                    f"{code}:{label}",
                    "pass" if ready else "fail",
                    f"{label_name} data is readable"
                    if ready
                    else f"{label_name} data is not readable",
                    f"grant the App {label_name} read access and retry doctor"
                    if not ready
                    else "",
                )
            )
    return probes


def _board_probes(
    loaded: EventsConfig,
    *,
    token: str,
    environ: Mapping[str, str],
    runner: CommandRunner,
) -> list[DoctorProbe]:
    probes: list[DoctorProbe] = []
    for board in loaded.boards:
        try:
            response = fetch_project_fields(
                board.key,
                env=credentials.env_with_token(dict(environ), token),
                runner=runner,
            )
        except ProjectFieldsIncomplete:
            probes.extend(
                (
                    DoctorProbe(
                        f"board-read:{board.key}",
                        "pass",
                        "configured project is readable",
                    ),
                    DoctorProbe(
                        f"board-fields:{board.key}",
                        "skip",
                        "Status and Priority fields could not be checked completely",
                        "retry after GitHub returns a complete project field list",
                    ),
                )
            )
            continue
        except RuntimeError:
            probes.extend(
                (
                    DoctorProbe(
                        f"board-read:{board.key}",
                        "fail",
                        "board credential cannot read the configured project",
                        "grant the credential project access and retry doctor",
                    ),
                    DoctorProbe(
                        f"board-fields:{board.key}",
                        "skip",
                        "Status and Priority fields could not be verified",
                        "restore board read access and retry doctor",
                    ),
                )
            )
            continue
        probes.append(
            DoctorProbe(
                f"board-read:{board.key}",
                "pass",
                "configured project is readable",
            )
        )
        fields = response.get("fields") if isinstance(response, dict) else None
        total_count = (
            response.get("totalCount") if isinstance(response, dict) else None
        )
        fields_complete = (
            isinstance(fields, list)
            and isinstance(total_count, int)
            and not isinstance(total_count, bool)
            and total_count == len(fields)
            and all(
                isinstance(item, dict) and isinstance(item.get("name"), str)
                for item in fields
            )
        )
        if not fields_complete:
            probes.append(
                DoctorProbe(
                    f"board-fields:{board.key}",
                    "skip",
                    "Status and Priority fields could not be checked completely",
                    "upgrade gh or reduce the project below the explicit field limit",
                )
            )
            continue
        assert isinstance(fields, list)
        names: set[str] = set()
        for item in fields:
            assert isinstance(item, dict)
            name = item.get("name")
            assert isinstance(name, str)
            names.add(name)
        fields_ready = {"Status", "Priority"} <= names
        probes.append(
            DoctorProbe(
                f"board-fields:{board.key}",
                "pass" if fields_ready else "fail",
                "Status and Priority fields are readable"
                if fields_ready
                else "Status or Priority field is missing or unreadable",
                "add readable Status and Priority fields to the project"
                if not fields_ready
                else "",
            )
        )
    return probes


def _secret_probe(environ: Mapping[str, str]) -> DoctorProbe:
    value = environ.get("AGENT_SESSION_WEBHOOK_SECRET_FILE", "").strip()
    if not value:
        return DoctorProbe(
            "webhook-secret",
            "skip",
            "webhook secret file is not configured",
            "set AGENT_SESSION_WEBHOOK_SECRET_FILE and retry doctor",
        )
    path = Path(value)
    path_result = _owner_only_path_probe(
        path, code="webhook-secret", kind="file"
    )
    if path_result.status != "pass":
        return path_result
    try:
        secret = path.read_bytes()
    except OSError:
        return DoctorProbe(
            "webhook-secret",
            "fail",
            "webhook secret file cannot be read",
            "grant the service account read access and retry doctor",
        )
    if secret.endswith(b"\n"):
        secret = secret[:-1]
    if not secret:
        return DoctorProbe(
            "webhook-secret",
            "fail",
            "webhook secret file is empty",
            "write the GitHub webhook secret to the protected file",
        )
    return DoctorProbe(
        "webhook-secret",
        "pass",
        "webhook secret file is owner-only and non-empty",
    )


def inspect_doctor(
    config_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
    runner: CommandRunner | None = None,
    read_credential_resolver: CredentialResolver | None = None,
) -> DoctorReport:
    """Run read-only configuration, SQLite, credential, and GitHub probes."""
    source_environ = os.environ if environ is None else environ
    command_runner = subprocess.run if runner is None else runner
    resolve_read = (
        credentials.resolve_read_credential
        if read_credential_resolver is None
        else read_credential_resolver
    )
    try:
        loaded = config.load(config_path)
    except (OSError, ValueError) as error:
        return DoctorReport(
            (
                DoctorProbe(
                    "configuration",
                    "fail",
                    f"configuration is invalid ({type(error).__name__})",
                    "correct the TOML file and retry doctor",
                ),
            )
        )

    probes = [DoctorProbe("configuration", "pass", "configuration is valid")]
    sqlite_probes, status = _sqlite_probes(loaded)
    probes.extend(sqlite_probes)
    if status is not None:
        probes.extend(_success_clock_probes(loaded, status))

    read_token, read_probe = _resolve_credential(
        "read-credential",
        source_environ,
        resolve_read,
        remedy="configure the installation read credential and retry doctor",
    )
    probes.append(read_probe)
    if read_token:
        probes.extend(
            _repository_probes(
                loaded,
                token=read_token,
                environ=source_environ,
                runner=command_runner,
            )
        )
    else:
        for repository in loaded.repositories:
            label = f"{repository.identity.owner}/{repository.identity.name}"
            probes.extend(
                (
                    DoctorProbe(
                        f"repository-read:{label}",
                        "skip",
                        "repository read was not attempted",
                        "configure the installation read credential and retry doctor",
                    ),
                    DoctorProbe(
                        f"repository-identity:{label}",
                        "skip",
                        "repository identity was not verified",
                        "configure the installation read credential and retry doctor",
                    ),
                    DoctorProbe(
                        f"checks-read:{label}",
                        "skip",
                        "check-run capability was not exercised",
                        "configure the installation read credential and retry doctor",
                    ),
                    DoctorProbe(
                        f"statuses-read:{label}",
                        "skip",
                        "combined-status capability was not exercised",
                        "configure the installation read credential and retry doctor",
                    ),
                )
            )

    if read_token:
        # Probe the credential a board read will actually use, not merely the read
        # token. Otherwise doctor warns that the board is unreadable on a deployment
        # where `DRIVER_GH_BOARD_TOKEN` is configured and the runtime reads it fine --
        # a false warning about the one path doctor exists to reassure you about.
        try:
            board_token = credentials.resolve_board_credential(
                source_environ, runner=command_runner
            )
        except RuntimeError:
            board_token = read_token
        probes.extend(
            _board_probes(
                loaded,
                token=board_token,
                environ=source_environ,
                runner=command_runner,
            )
        )
    else:
        for board in loaded.boards:
            probes.extend(
                (
                    DoctorProbe(
                        f"board-read:{board.key}",
                        "skip",
                        "board read was not attempted",
                        "configure the shared read credential and retry doctor",
                    ),
                    DoctorProbe(
                        f"board-fields:{board.key}",
                        "skip",
                        "Status and Priority fields were not verified",
                        "configure the shared read credential and retry doctor",
                    ),
                )
            )
    probes.append(_secret_probe(source_environ))
    return DoctorReport(tuple(probes))


def doctor(
    config_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
    runner: CommandRunner | None = None,
    read_credential_resolver: CredentialResolver | None = None,
) -> int:
    report = inspect_doctor(
        config_path,
        environ=environ,
        runner=runner,
        read_credential_resolver=read_credential_resolver,
    )
    for probe in report.probes:
        line = f"[{probe.status}] {probe.code}: {probe.message}"
        if probe.remedy:
            line += f"; remedy: {probe.remedy}"
        print(line)
    return report.exit_code


def queue_status(
    database: Path, *, busy_timeout_ms: int, as_json: bool, now: datetime
) -> int:
    status = QueueStore.open(database, busy_timeout_ms=busy_timeout_ms).status(
        now=now
    )
    values = {
        "schema_version": status.schema_version,
        "backlog_count": status.backlog_count,
        "oldest_dirty_at": _timestamp(status.oldest_dirty_at),
        "oldest_age_seconds": _age_seconds(status.oldest_dirty_at, now),
        "leased_count": status.leased_count,
        "backed_off_count": status.backed_off_count,
        "latest_delivery_at": _timestamp(status.latest_delivery_at),
        "latest_delivery_age_seconds": _age_seconds(status.latest_delivery_at, now),
        "watch_count": status.watch_count,
        "recent_errors": list(status.recent_errors),
        "repositories": [
            {
                "repository_id": item.repository_id,
                "last_hint_at": _timestamp(item.last_hint_at),
                "last_hint_age_seconds": _age_seconds(item.last_hint_at, now),
                "last_scan_started_at": _timestamp(item.last_scan_started_at),
                "last_scan_started_age_seconds": _age_seconds(
                    item.last_scan_started_at, now
                ),
                "last_scan_success_at": _timestamp(item.last_scan_success_at),
                "last_scan_success_age_seconds": _age_seconds(
                    item.last_scan_success_at, now
                ),
                "scan_lease_owner": item.scan_lease_owner,
                "scan_lease_until": _timestamp(item.scan_lease_until),
                "last_error": item.last_error,
            }
            for item in status.repositories
        ],
        "pollers": [
            {
                "source_key": item.source_key,
                "last_success_at": _timestamp(item.last_success_at),
                "last_success_age_seconds": _age_seconds(
                    item.last_success_at, now
                ),
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
        oldest = (
            "unknown"
            if values["oldest_age_seconds"] is None
            else f"{values['oldest_age_seconds']}s"
        )
        latest = (
            "never"
            if status.latest_delivery_at is None
            else status.latest_delivery_at.isoformat()
        )
        latest_age = values["latest_delivery_age_seconds"]
        latest_age_text = "unknown" if latest_age is None else f"{latest_age}s"
        print(
            f"backlog={status.backlog_count} oldest-age={oldest} "
            f"leases={status.leased_count} backoff={status.backed_off_count} "
            f"latest-delivery={latest} latest-delivery-age={latest_age_text} "
            f"watches={status.watch_count} schema={status.schema_version}"
        )
        for repository in status.repositories:
            last_hint = _timestamp(repository.last_hint_at) or "unknown"
            scan_started = _timestamp(repository.last_scan_started_at) or "never"
            scan_success = _timestamp(repository.last_scan_success_at) or "never"
            scan_success_age = _age_seconds(repository.last_scan_success_at, now)
            scan_lease = repository.scan_lease_owner or "none"
            scan_lease_until = _timestamp(repository.scan_lease_until) or "never"
            error = repository.last_error or "none"
            age = "unknown" if scan_success_age is None else f"{scan_success_age}s"
            print(
                f"repository={repository.repository_id} last-hint={last_hint} "
                f"scan-started={scan_started} scan-success={scan_success} "
                f"scan-success-age={age} scan-lease={scan_lease} "
                f"scan-lease-until={scan_lease_until} last-error={error}"
            )
        for poller in status.pollers:
            success = _timestamp(poller.last_success_at) or "never"
            success_age = _age_seconds(poller.last_success_at, now)
            lease = poller.lease_owner or "none"
            lease_until = _timestamp(poller.lease_until) or "never"
            age = "unknown" if success_age is None else f"{success_age}s"
            error = poller.last_error or "none"
            print(
                f"poller={poller.source_key} last-success={success} "
                f"last-success-age={age} lease={lease} "
                f"lease-until={lease_until} last-error={error}"
            )
        print(
            f"recent-errors={'; '.join(status.recent_errors) if status.recent_errors else 'none'}"
        )
    return 0


def prune(
    database: Path,
    *,
    busy_timeout_ms: int,
    deliveries_before: datetime,
    invalidations_before: datetime,
) -> int:
    result = QueueStore.open(database, busy_timeout_ms=busy_timeout_ms).prune(
        deliveries_before=deliveries_before,
        invalidations_before=invalidations_before,
    )
    print(
        f"pruned deliveries={result.deliveries_deleted} "
        f"invalidations={result.invalidations_deleted}"
    )
    return 0
