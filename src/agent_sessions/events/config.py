"""Strict, credential-free configuration for the events queue."""

from __future__ import annotations

import tomllib
from datetime import timedelta
from pathlib import Path
from typing import Any

from .models import BoardConfig, EventsConfig, RepositoryConfig, RepositoryIdentity, ScanPolicy

_TOP_LEVEL = {
    "database", "busy_timeout_ms", "claim_limit", "claim_lease_seconds", "retry_base_seconds",
    "retry_max_seconds", "max_body_bytes", "delivery_retention_days", "invalidation_retention_days",
    "scan", "repositories", "boards",
}
_SCALAR = _TOP_LEVEL - {"scan", "repositories", "boards"}
_SCAN = {"quiet_period_seconds", "interval_seconds", "maximum_age_seconds"}
_REPOSITORY = {"id", "owner", "name", "installation_id"}
_BOARD = {"owner", "number", "repository_ids"}


def _expect_keys(value: dict[str, Any], allowed: set[str], label: str, *, optional: set[str] = set()) -> None:
    unknown = set(value) - allowed
    missing = allowed - optional - set(value)
    if unknown:
        raise ValueError(f"unknown {label} key: {sorted(unknown)[0]}")
    if missing:
        raise ValueError(f"missing {label} key: {sorted(missing)[0]}")


def _positive(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _owner_name(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "/" in value or value in {".", ".."}:
        raise ValueError(f"{name} must use the GitHub owner/name shape")
    return value


def _table_array(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{name} must be an array of tables")
    return value


def load(path: Path) -> EventsConfig:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    _expect_keys(raw, _TOP_LEVEL, "configuration")
    database_value = raw["database"]
    if not isinstance(database_value, str):
        raise ValueError("database must be an absolute path string")
    database = Path(database_value)
    if not database.is_absolute():
        raise ValueError("database path must be absolute")
    values = {name: _positive(raw[name], name) for name in _SCALAR if name != "database"}
    scan_raw = raw["scan"]
    if not isinstance(scan_raw, dict):
        raise ValueError("scan must be a table")
    _expect_keys(scan_raw, _SCAN, "scan")
    scan_values = {name: _positive(scan_raw[name], name) for name in _SCAN}
    if scan_values["maximum_age_seconds"] < scan_values["interval_seconds"]:
        raise ValueError("maximum_age_seconds must be at least interval_seconds")
    repositories: list[RepositoryConfig] = []
    ids: set[int] = set()
    names: set[tuple[str, str]] = set()
    for item in _table_array(raw["repositories"], "repositories"):
        _expect_keys(item, _REPOSITORY, "repository", optional={"installation_id"})
        identity = RepositoryIdentity(
            id=_positive(item["id"], "repository id"),
            owner=_owner_name(item["owner"], "repository owner"),
            name=_owner_name(item["name"], "repository name"),
            installation_id=None if item.get("installation_id") is None else _positive(item["installation_id"], "installation_id"),
        )
        pair = (identity.owner.lower(), identity.name.lower())
        if identity.id in ids or pair in names:
            raise ValueError("duplicate repository id or owner/name")
        ids.add(identity.id)
        names.add(pair)
        repositories.append(RepositoryConfig(identity))
    boards: list[BoardConfig] = []
    for item in _table_array(raw["boards"], "boards"):
        _expect_keys(item, _BOARD, "board")
        raw_repository_ids = item["repository_ids"]
        if not isinstance(raw_repository_ids, list):
            raise ValueError("board repository_ids must be an array")
        repository_ids = tuple(_positive(repository_id, "board repository id") for repository_id in raw_repository_ids)
        if any(repository_id not in ids for repository_id in repository_ids):
            raise ValueError("board references an unknown repository")
        boards.append(BoardConfig(_owner_name(item["owner"], "board owner"), _positive(item["number"], "board number"), repository_ids))
    return EventsConfig(
        database=database,
        busy_timeout_ms=values["busy_timeout_ms"], claim_limit=values["claim_limit"],
        claim_lease=timedelta(seconds=values["claim_lease_seconds"]), retry_base=timedelta(seconds=values["retry_base_seconds"]),
        retry_maximum=timedelta(seconds=values["retry_max_seconds"]), max_body_bytes=values["max_body_bytes"],
        delivery_retention=timedelta(days=values["delivery_retention_days"]),
        invalidation_retention=timedelta(days=values["invalidation_retention_days"]),
        scan=ScanPolicy(timedelta(seconds=scan_values["quiet_period_seconds"]), timedelta(seconds=scan_values["interval_seconds"]), timedelta(seconds=scan_values["maximum_age_seconds"])),
        repositories=tuple(repositories), boards=tuple(boards),
    )
