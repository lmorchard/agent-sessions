"""One-pass Projects V2 and approval-reaction pollers."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from .github import (
    ApprovalPredicateObservation,
    CompleteProjectSnapshot,
    GitHubReadStopped,
    fetch_approval_predicates,
    fetch_project_items,
)
from .models import (
    ApprovalWatch,
    BoardConfig,
    EventsConfig,
    Invalidation,
    JSONValue,
    PollFailure,
    ProjectItemProjection,
    RepositoryConfig,
)
from .store import QueueStore


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _never_stop() -> bool:
    return False


@dataclass(frozen=True)
class PollRunResult:
    attempted: int = 0
    skipped: int = 0
    invalidations: int = 0
    errors: tuple[str, ...] = ()

    @property
    def exit_code(self) -> int:
        return 1 if self.errors else 0


def _project_invalidation(
    item: ProjectItemProjection,
    reason: str,
    diagnostic: Mapping[str, JSONValue],
) -> Invalidation:
    details: dict[str, JSONValue] = {
        "board_key": item.board_key,
        "item_node_id": item.item_node_id,
    }
    details.update(diagnostic)
    return Invalidation(
        item.repository_id,
        item.content_kind,
        str(item.content_number),
        reason,
        details,
    )


def diff_project_snapshot(
    before: Iterable[ProjectItemProjection],
    after: Iterable[ProjectItemProjection],
) -> tuple[Invalidation, ...]:
    """Return one invalidation per changed routing target."""
    old = {item.item_node_id: item for item in before}
    new = {item.item_node_id: item for item in after}
    invalidations: dict[tuple[int, str, int], Invalidation] = {}
    for item_node_id in sorted(old.keys() | new.keys()):
        prior = old.get(item_node_id)
        current = new.get(item_node_id)
        if prior is None and current is not None:
            item = current
            invalidation = _project_invalidation(
                item, "project_membership_added", {}
            )
        elif current is None and prior is not None:
            item = prior
            invalidation = _project_invalidation(
                item, "project_membership_removed", {}
            )
        elif prior is not None and current is not None:
            fields: list[JSONValue] = [
                field
                for field in ("status", "priority")
                if getattr(prior, field) != getattr(current, field)
            ]
            if not fields:
                continue
            item = current
            invalidation = _project_invalidation(
                item, "project_fields_changed", {"fields": fields}
            )
        else:  # pragma: no cover - the key comes from the union above
            continue
        invalidations.setdefault(
            (item.repository_id, item.content_kind, item.content_number), invalidation
        )
    return tuple(invalidations.values())


def poll_projects_once(
    config: EventsConfig,
    store: QueueStore,
    token: str,
    *,
    worker_id: str,
    now: datetime,
    fetcher: Callable[[BoardConfig, str], CompleteProjectSnapshot] | None = None,
    clock: Callable[[], datetime] = _utc_now,
    stop_requested: Callable[[], bool] = _never_stop,
) -> PollRunResult:
    """Poll every configured board once, under an independent source lease."""
    attempted = skipped = invalidation_count = 0
    errors: list[str] = []
    for board in config.boards:
        if stop_requested():
            break
        source_key = f"projects:{board.key}"
        if not store.acquire_poller_lease(
            source_key,
            worker_id=worker_id,
            lease_until=now + config.claim_lease,
            now=now,
        ):
            skipped += 1
            continue
        attempted += 1
        try:
            snapshot = (
                fetch_project_items(
                    board,
                    token,
                    stop_requested=stop_requested,
                )
                if fetcher is None
                else fetcher(board, token)
            )
            if snapshot.board_key != board.key:
                raise PollFailure("project snapshot belongs to a different board")
            established = store.poller_last_success_at(source_key) is not None
            before = tuple(
                item
                for item in store.project_snapshot(board.key)
                if item.repository_id in board.repository_ids
            )
            invalidations = (
                diff_project_snapshot(before, snapshot.items) if established else ()
            )
            committed_at = clock()
            if not store.replace_project_snapshot_if_leased(
                source_key,
                worker_id=worker_id,
                board_key=board.key,
                projections=snapshot.items,
                invalidations=invalidations,
                now=committed_at,
            ):
                raise PollFailure("project poller lease was lost during fetch")
            store.finish_poller(
                source_key,
                worker_id=worker_id,
                succeeded=True,
                now=committed_at,
            )
            invalidation_count += len(invalidations)
        except GitHubReadStopped:
            store.finish_poller(
                source_key,
                worker_id=worker_id,
                succeeded=False,
                now=clock(),
            )
            break
        except Exception as error:  # every failed source must release its lease and fail the pass
            message = f"{source_key}: {error}"
            errors.append(message)
            store.finish_poller(
                source_key,
                worker_id=worker_id,
                succeeded=False,
                now=clock(),
                error=str(error),
            )
    return PollRunResult(attempted, skipped, invalidation_count, tuple(errors))


def poll_reactions_once(
    config: EventsConfig,
    store: QueueStore,
    token: str,
    bot_logins: frozenset[str],
    *,
    worker_id: str,
    now: datetime,
    fetcher: Callable[
        [RepositoryConfig, tuple[ApprovalWatch, ...], str, frozenset[str]],
        tuple[ApprovalPredicateObservation, ...],
    ]
    | None = None,
    clock: Callable[[], datetime] = _utc_now,
    stop_requested: Callable[[], bool] = _never_stop,
) -> PollRunResult:
    """Poll active approval watches once, under one lease per repository."""
    attempted = skipped = invalidation_count = 0
    errors: list[str] = []
    for repository in config.repositories:
        if stop_requested():
            break
        repository_id = repository.identity.id
        watches = store.list_watches(repository_id)
        if not watches:
            continue
        source_key = f"reactions:{repository_id}"
        if not store.acquire_poller_lease(
            source_key,
            worker_id=worker_id,
            lease_until=now + config.claim_lease,
            now=now,
        ):
            skipped += 1
            continue
        attempted += 1
        try:
            observations = (
                fetch_approval_predicates(
                    repository,
                    watches,
                    token,
                    bot_logins,
                    stop_requested=stop_requested,
                )
                if fetcher is None
                else fetcher(repository, watches, token, bot_logins)
            )
            expected = {
                (item.repository_id, item.issue_number, item.predicate, item.parked_at)
                for item in watches
            }
            actual = {
                (
                    item.watch.repository_id,
                    item.watch.issue_number,
                    item.watch.predicate,
                    item.watch.parked_at,
                )
                for item in observations
            }
            if len(observations) != len(watches) or actual != expected:
                raise PollFailure("approval fetch did not resolve every active watch")
            completed_at = now
            for observation in observations:
                observed_at = clock()
                changed = store.record_watch_observation_if_leased(
                    source_key,
                    worker_id=worker_id,
                    watch=observation.watch,
                    value=observation.value,
                    observed_at=observed_at,
                )
                if changed is None:
                    raise PollFailure(
                        "reaction poller lease or watch state changed during fetch"
                    )
                invalidation_count += int(changed)
                completed_at = observed_at
            store.finish_poller(
                source_key,
                worker_id=worker_id,
                succeeded=True,
                now=completed_at,
            )
        except GitHubReadStopped:
            store.finish_poller(
                source_key,
                worker_id=worker_id,
                succeeded=False,
                now=clock(),
            )
            break
        except Exception as error:  # failed fetches preserve observations and fail the pass
            errors.append(f"{source_key}: {error}")
            store.finish_poller(
                source_key,
                worker_id=worker_id,
                succeeded=False,
                now=clock(),
                error=str(error),
            )
    return PollRunResult(attempted, skipped, invalidation_count, tuple(errors))
