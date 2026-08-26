"""Immutable values shared by event-queue components."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Mapping, TypeAlias

TargetKind = Literal["issue", "pull_request", "revision", "repository", "installation"]
JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


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
    retry_count: int = 0


@dataclass(frozen=True)
class ScanPolicy:
    quiet_period: timedelta
    interval: timedelta
    maximum_age: timedelta


@dataclass(frozen=True)
class PollingPolicy:
    projects_interval: timedelta
    reactions_interval: timedelta


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
    polling: PollingPolicy
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
class RepositoryStatus:
    repository_id: int
    last_hint_at: datetime | None
    last_scan_started_at: datetime | None
    last_scan_success_at: datetime | None
    scan_lease_owner: str | None
    scan_lease_until: datetime | None
    last_error: str


@dataclass(frozen=True)
class PollerStatus:
    source_key: str
    last_success_at: datetime | None
    lease_owner: str | None
    lease_until: datetime | None
    last_error: str


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
class PruneResult:
    deliveries_deleted: int
    invalidations_deleted: int
    checkpoint_busy: int
    checkpoint_log_frames: int
    checkpointed_frames: int


class QueueBusy(RuntimeError):
    pass


class QueueUnavailable(RuntimeError):
    pass


class IncompatibleSchema(RuntimeError):
    pass


class PollFailure(RuntimeError):
    pass
