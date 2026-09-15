"""Queue-first driver selection and repository scan scheduling."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from agent_sessions.driver import credentials, gh_query, lifecycle, reconciler, router
from agent_sessions.driver.labels import PARK_LABEL

from .github import (
    GitHubPermanentError,
    GitHubTransientError,
    LiveTargetResolver,
    fetch_board_items,
)
from .models import ClaimedTarget, EventsConfig, Invalidation, RepositoryConfig, ScanPolicy
from .store import QueueStore

#: Beyond this many doublings the delay has saturated for any realistic configuration,
#: so the shift is clamped rather than evaluated. 2.0**64 is a finite float, which is
#: what makes the multiply below total.
_RETRY_SHIFT_CAP = 64


def retry_delay(base: timedelta, maximum: timedelta, retry_count: int) -> timedelta:
    """Capped exponential backoff that cannot raise.

    The previous expression was `min(base * (2**retry_count), maximum)`, which evaluates
    the multiply *before* the cap -- and `base` is a `timedelta`, not a number, so it
    overflows instead of saturating::

        41  ->  0:30:00
        42  ->  OverflowError: days=1527099483; must have magnitude <= 999999999

    With the example configuration the delay is already pinned at `maximum` from the
    sixth attempt onward, so every shift past that was waste until it threw. And
    `OverflowError` is not in `lifecycle._queue_failure_types()`, so it escaped
    uncaught, the row was never acknowledged, and the repository's driver wedged on
    every subsequent run with no fallback to the legacy scan.

    Arithmetic happens in seconds so the growth is float rather than `timedelta`, and
    the clamp is applied before converting back. Both together make this total for any
    `retry_count`, including a negative one.
    """
    shift = min(max(retry_count, 0), _RETRY_SHIFT_CAP)
    seconds = min(base.total_seconds() * (2.0**shift), maximum.total_seconds())
    return timedelta(seconds=max(seconds, 0.0))


@dataclass(frozen=True)
class RepositoryScanState:
    last_hint_at: datetime | None
    last_scan_success_at: datetime | None
    scan_lease_owner: str | None
    scan_lease_until: datetime | None


@dataclass
class QueueRuntime:
    config: EventsConfig
    store: QueueStore
    repository: RepositoryConfig


@dataclass
class QueueSelection:
    selection: lifecycle.SelectionResult | None
    selected_claim: ClaimedTarget | None
    acknowledged: tuple[ClaimedTarget, ...]
    released: tuple[ClaimedTarget, ...]
    retried: tuple[ClaimedTarget, ...]
    used_full_scan: bool


def scan_decision(
    *,
    now: datetime,
    state: RepositoryScanState,
    has_immediately_eligible_target: bool,
    policy: ScanPolicy,
) -> Literal["hard-deadline", "quiet-period", "not-due"]:
    if state.last_scan_success_at is None:
        return "hard-deadline"
    age = now - state.last_scan_success_at
    if age >= policy.maximum_age:
        return "hard-deadline"
    if has_immediately_eligible_target:
        return "not-due"
    if state.last_hint_at is not None and now - state.last_hint_at < policy.quiet_period:
        return "not-due"
    if age >= policy.interval:
        return "quiet-period"
    return "not-due"


def _repository_state(runtime: QueueRuntime, now: datetime) -> RepositoryScanState:
    status = runtime.store.status(now=now)
    found = next(
        (
            repository
            for repository in status.repositories
            if repository.repository_id == runtime.repository.identity.id
        ),
        None,
    )
    if found is None:
        return RepositoryScanState(None, None, None, None)
    return RepositoryScanState(
        found.last_hint_at,
        found.last_scan_success_at,
        found.scan_lease_owner,
        found.scan_lease_until,
    )


def _full_scan(
    ctx: lifecycle.RunContext,
    runtime: QueueRuntime,
    *,
    now: datetime,
    worker_id: str,
) -> QueueSelection | None:
    repository_id = runtime.repository.identity.id
    if not runtime.store.acquire_scan_lease(
        repository_id,
        worker_id=worker_id,
        lease_until=now + runtime.config.claim_lease,
        now=now,
    ):
        return None
    try:
        selection = lifecycle.select_queue(ctx, approval_watch_runtime=runtime)
    except Exception as error:
        runtime.store.finish_scan(
            repository_id,
            worker_id=worker_id,
            succeeded=False,
            now=now,
            error=str(error),
        )
        raise
    if not selection.issue_snapshot_complete:
        from agent_sessions.driver import agent_session_driver

        agent_session_driver.release_lock(
            ctx.repo_path,
            write_env=credentials.repository_write_env(dict(os.environ), ctx.creds),
        )
        runtime.store.finish_scan(
            repository_id,
            worker_id=worker_id,
            succeeded=False,
            now=now,
            error="authoritative issue snapshot incomplete",
        )
        return None
    runtime.store.finish_scan(
        repository_id,
        worker_id=worker_id,
        succeeded=True,
        now=now,
    )
    return QueueSelection(selection, None, (), (), (), True)


def _labels(issue: dict) -> set[str]:
    return {
        str(label.get("name"))
        for label in issue.get("labels", [])
        if isinstance(label, dict) and label.get("name")
    }


def _attempts(issue: dict) -> int:
    names = _labels(issue)
    for count in (3, 2, 1):
        if f"agent-session:attempt-{count}" in names:
            return count
    return 0


def _pr_details(pull_request: dict, driver_bots: frozenset[str]) -> dict:
    failed_ci, pending_ci = gh_query.parse_pr_ci_status(pull_request)
    requested, reviewed, decision = gh_query.parse_pr_reviews(pull_request)
    return {
        "unresolved": int(pull_request.get("unresolvedThreads", 0) or 0),
        "failed_ci": failed_ci,
        "pending_ci": pending_ci,
        "req_rev": requested,
        "revd": reviewed,
        "rev_decision": decision,
        "merge_state_status": pull_request.get("mergeStateStatus"),
        "mergeable": pull_request.get("mergeable"),
        "has_new_human_comment": gh_query.parse_pr_human_comments(
            pull_request, driver_bots
        ),
    }


def _github_time(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _human_comment(
    issue: dict,
    driver_bots: frozenset[str],
    parked_at: datetime | None,
) -> tuple[bool, str]:
    if parked_at is None:
        return False, ""

    issue_number = str(issue.get("number", ""))

    def decision_for(login: object, timestamp: object) -> tuple[bool, str]:
        observed_at = _github_time(timestamp)
        author = str(login or "")
        if observed_at is None or observed_at <= parked_at:
            return False, ""
        event = reconciler.PollingAdapter.synthesize_comment_event(
            issue_number,
            [{"author": {"login": author}, "createdAt": str(timestamp)}],
        )
        if event is None:
            return False, ""
        event.is_bot = credentials.is_bot_login(author, known_bots=set(driver_bots))
        decision = reconciler.handle_event(event)
        return (decision.action == "unpark", decision.author)

    comments = [
        comment for comment in issue.get("comments", []) if isinstance(comment, dict)
    ]
    for comment in reversed(comments):
        author = comment.get("author") or comment.get("user") or {}
        login = author.get("login", "") if isinstance(author, dict) else ""
        found = decision_for(login, comment.get("createdAt") or comment.get("created_at"))
        if found[0]:
            return found
        reactions = comment.get("reactions") or {}
        nodes = reactions.get("nodes", []) if isinstance(reactions, dict) else reactions
        if not isinstance(nodes, list):
            continue
        for reaction in reversed(nodes):
            if not isinstance(reaction, dict):
                continue
            user = reaction.get("user") or {}
            login = user.get("login", "") if isinstance(user, dict) else ""
            found = decision_for(
                login,
                reaction.get("createdAt") or reaction.get("created_at"),
            )
            if found[0]:
                return found
    return False, ""


def select_work(
    ctx: lifecycle.RunContext,
    runtime: QueueRuntime | None,
    *,
    now: datetime,
    worker_id: str,
) -> QueueSelection:
    """Reconcile bounded dirty hints and return at most one locked candidate."""
    if runtime is None:
        return QueueSelection(lifecycle.select_queue(ctx), None, (), (), (), True)

    if ctx.issue or ctx.retry:
        manual_scan = _full_scan(ctx, runtime, now=now, worker_id=worker_id)
        if manual_scan is not None:
            return manual_scan
        # The scan lease was held by another worker. It exists to stop two workers
        # running the same *full scan*, not to arbitrate an explicit operator request,
        # and mutual exclusion on the issue itself is the git-ref lock's job -- which
        # this run still takes. Returning an empty selection here reported "nothing
        # eligible; no runs attempted", which is the opposite of what happened, for up
        # to the claim lease. So fall through and select, the way the hard-deadline path
        # below already does when it cannot take the lease.
        return QueueSelection(
            lifecycle.select_queue(ctx, approval_watch_runtime=runtime),
            None,
            (),
            (),
            (),
            True,
        )

    state = _repository_state(runtime, now)
    if (
        scan_decision(
            now=now,
            state=state,
            has_immediately_eligible_target=False,
            policy=runtime.config.scan,
        )
        == "hard-deadline"
    ):
        full_scan = _full_scan(ctx, runtime, now=now, worker_id=worker_id)
        if full_scan is not None:
            return full_scan

    claims = runtime.store.claim_targets(
        runtime.repository.identity.id,
        worker_id=worker_id,
        limit=runtime.config.claim_limit,
        lease_until=now + runtime.config.claim_lease,
        now=now,
    )
    resolver = LiveTargetResolver(read_token=ctx.creds.read_token)
    acknowledged: list[ClaimedTarget] = []
    released: list[ClaimedTarget] = []
    retried: list[ClaimedTarget] = []
    issues: dict[str, dict] = {}
    pull_requests: dict[str, dict] = {}
    board_items: dict[str, dict] = {}
    claims_by_issue: dict[str, list[ClaimedTarget]] = {}

    for current_claim in claims:
        try:
            resolved = resolver.resolve(runtime.repository, current_claim)
        except GitHubTransientError as error:
            delay = retry_delay(
                runtime.config.retry_base,
                runtime.config.retry_maximum,
                current_claim.retry_count,
            )
            runtime.store.retry(
                current_claim,
                error=str(error),
                next_attempt_at=now + delay,
            )
            retried.append(current_claim)
            continue
        except GitHubPermanentError:
            runtime.store.acknowledge(current_claim)
            acknowledged.append(current_claim)
            continue

        if resolved.irrelevant_reason or resolved.control_plane_only or not resolved.issues:
            runtime.store.acknowledge(current_claim)
            acknowledged.append(current_claim)
            continue

        for issue in resolved.issues:
            number = str(issue.get("number", ""))
            if not number:
                continue
            issues[number] = issue
            claims_by_issue.setdefault(number, []).append(current_claim)
        for pull_request in resolved.pull_requests:
            number = str(pull_request.get("number", ""))
            if number:
                pull_requests[number] = pull_request
        for item in resolved.board_items:
            item_id = str(item.get("id", ""))
            if item_id:
                board_items[item_id] = item

    from agent_sessions.driver import agent_session_driver

    if issues and ctx.board:
        try:
            current_board_items = fetch_board_items(
                ctx.board,
                env=credentials.board_read_env(dict(os.environ), ctx.creds),
            )
        except GitHubTransientError as error:
            for current_claim in claims:
                if current_claim in acknowledged or current_claim in retried:
                    continue
                delay = retry_delay(
                    runtime.config.retry_base,
                    runtime.config.retry_maximum,
                    current_claim.retry_count,
                )
                runtime.store.retry(
                    current_claim,
                    error=str(error),
                    next_attempt_at=now + delay,
                )
                retried.append(current_claim)
            return QueueSelection(
                None,
                None,
                tuple(acknowledged),
                tuple(released),
                tuple(retried),
                False,
            )
        for item in current_board_items:
            item_id = str(item.get("id", ""))
            if item_id:
                board_items[item_id] = item

    if issues:
        parked_nums = {
            number for number, issue in issues.items() if PARK_LABEL in _labels(issue)
        }
        watch_times = {
            str(watch.issue_number): watch.parked_at
            for watch in runtime.store.list_watches(runtime.repository.identity.id)
        }
        selection_data = router.select(
            open_issues=list(issues.values()),
            open_prs=list(pull_requests.values()),
            board_items=list(board_items.values()),
            parked_nums=parked_nums,
            park_reasons={
                number: "awaiting human input" for number in parked_nums
            },
            attempts_map={number: _attempts(issue) for number, issue in issues.items()},
            human_comments_map={
                number: _human_comment(issue, ctx.driver_bots, watch_times.get(number))
                for number, issue in issues.items()
                if number in parked_nums
            },
            pr_details_map={
                number: _pr_details(pull_request, ctx.driver_bots)
                for number, pull_request in pull_requests.items()
            },
            config={
                "repo": ctx.repo,
                "all_issues": ctx.all_issues,
                "max_phase_attempts": ctx.max_phase_attempts,
                "retry": ctx.retry,
                "issue": ctx.issue,
            },
        )
    else:
        selection_data = {
            "candidates": [],
            "messages": [],
            "unpark_actions": [],
            "park_actions": [],
        }

    for message in selection_data["messages"]:
        lifecycle.say(message)

    for number in selection_data["unpark_actions"]:
        agent_session_driver.park_label_remove(
            number,
            ctx.repo,
            write_env=credentials.repository_write_env(dict(os.environ), ctx.creds),
        )
        try:
            if lifecycle.authoritative_issue_is_parked(ctx, str(number)):
                continue
            runtime.store.remove_watch(
                runtime.repository.identity.id,
                int(number),
            )
        except Exception as error:
            lifecycle.report_approval_watch_failure(error)
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    for number, reason in selection_data["park_actions"]:
        agent_session_driver.apply_park_state(
            number,
            "parked",
            timestamp,
            f"parked by loop breaker: {reason}",
            ctx.repo,
            ctx.state_dir,
            ctx.parked_log,
            quiet=True,
            write_env=credentials.repository_write_env(dict(os.environ), ctx.creds),
        )

    candidate_numbers = {str(number) for number, _phase in selection_data["candidates"]}
    candidate_claims = {
        current_claim
        for number in candidate_numbers
        for current_claim in claims_by_issue.get(number, [])
    }
    for issue_claims in claims_by_issue.values():
        for current_claim in issue_claims:
            if current_claim in candidate_claims or current_claim in acknowledged:
                continue
            runtime.store.acknowledge(current_claim)
            acknowledged.append(current_claim)

    candidate_issues_by_claim = {
        current_claim: {
            number
            for number in candidate_numbers
            if current_claim in claims_by_issue.get(number, [])
        }
        for current_claim in candidate_claims
    }

    selected: tuple[str, str] | None = None
    selected_claim: ClaimedTarget | None = None
    for number, phase in selection_data["candidates"]:
        issue_claims = claims_by_issue.get(str(number), [])
        if not issue_claims:
            continue
        if not agent_session_driver.acquire_lock(
            number,
            phase,
            ctx.repo_path,
            read_env=credentials.driver_env(dict(os.environ), ctx.creds),
            write_env=credentials.repository_write_env(dict(os.environ), ctx.creds),
        ):
            lifecycle.say(
                f"  SKIP    #{number}  lock contention (another agent holds or held lock)"
            )
            continue
        selected = (str(number), phase)
        selected_claim = issue_claims[0]
        for duplicate in issue_claims[1:]:
            if candidate_issues_by_claim.get(duplicate) == {selected[0]}:
                runtime.store.acknowledge(duplicate)
                acknowledged.append(duplicate)
        break

    if selected is not None and selected_claim is not None:
        sibling_numbers = sorted(
            candidate_issues_by_claim.get(selected_claim, set()) - {selected[0]},
            key=int,
        )
        if sibling_numbers:
            diagnostic = {
                "source_target_kind": selected_claim.target_kind,
                "source_target_key": selected_claim.target_key,
            }
            if selected_claim.target_kind == "pull_request":
                diagnostic["source_pull_request"] = selected_claim.target_key
            runtime.store.enqueue_synthetic(
                "claim_resolution",
                (
                    f"{selected_claim.target_kind}:{selected_claim.repository_id}:"
                    f"{selected_claim.target_key}:{selected_claim.generation}"
                ),
                (
                    Invalidation(
                        selected_claim.repository_id,
                        "issue",
                        number,
                        "unselected_closing_issue",
                        diagnostic,
                    )
                    for number in sibling_numbers
                ),
                now=now,
            )

    for current_claim in claims:
        if current_claim == selected_claim:
            continue
        if (
            current_claim in acknowledged
            or current_claim in released
            or current_claim in retried
        ):
            continue
        runtime.store.release(current_claim)
        released.append(current_claim)

    if selected is None:
        current_state = _repository_state(runtime, now)
        if (
            scan_decision(
                now=now,
                state=current_state,
                has_immediately_eligible_target=False,
                policy=runtime.config.scan,
            )
            == "quiet-period"
        ):
            full_scan = _full_scan(ctx, runtime, now=now, worker_id=worker_id)
            if full_scan is not None:
                full_scan.acknowledged = tuple(acknowledged)
                full_scan.released = tuple(released)
                full_scan.retried = tuple(retried)
                return full_scan
        return QueueSelection(
            None,
            None,
            tuple(acknowledged),
            tuple(released),
            tuple(retried),
            False,
        )

    item_ids = {
        str(item.get("content", {}).get("number")): str(item.get("id"))
        for item in board_items.values()
        if isinstance(item.get("content"), dict) and item.get("id")
    }
    selection = lifecycle.SelectionResult(
        open_prs=list(pull_requests.values()),
        candidates=[selected],
        board_item_ids=item_ids,
    )
    return QueueSelection(
        selection,
        selected_claim,
        tuple(acknowledged),
        tuple(released),
        tuple(retried),
        False,
    )
