#!/usr/bin/env python3
"""Reactive reconciler module for the agent-session driver.

Separates event-driven reconciler transitions (issue comment unpark,
PR thread review comments, PR CI status, PR reviews) from cron-shaped polling/scheduling.

Handlers take plain event structs (`ReconcilerEvent`) and return decision structs
(`ReconcilerDecision`), performing zero I/O and zero subprocess / `gh` calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReconcilerEvent:
    """Plain data struct representing a reconciler event."""

    event_type: str  # "issue_comment", "pull_request_review_comment", "check_suite", "pull_request_review", "pull_request"
    issue_number: str
    pr_number: str = ""
    unresolved_threads: int = 0
    failed_ci: int = 0
    pending_ci: int = 0
    review_requests: int = 0
    reviews: int = 0
    author_login: str = ""
    is_bot: bool = False
    timestamp: str = ""
    has_conflict: bool = False
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReconcilerDecision:
    """Plain data struct representing a decision reached by a handler."""

    action: str  # "unpark", "eligible", "skip", "ignore"
    issue_number: str
    phase: str = ""  # "address_comments", "fix_ci", "wait_ci", "request_review", "grade_gate"
    pr_number: str = ""
    author: str = ""
    reason: str = ""


def handle_issue_comment(event: ReconcilerEvent) -> ReconcilerDecision:
    """Handle an issue comment event (e.g. unpark on new human comment)."""
    if not event.is_bot and event.author_login:
        return ReconcilerDecision(
            action="unpark",
            issue_number=event.issue_number,
            author=event.author_login,
            reason=f"new comment from @{event.author_login} detected",
        )
    return ReconcilerDecision(
        action="ignore",
        issue_number=event.issue_number,
        reason="comment is from bot or has no author",
    )


def handle_pr_reconcile(event: ReconcilerEvent) -> ReconcilerDecision:
    """Handle reactive PR state transitions (threads, CI status, reviews)."""
    if event.has_conflict:
        return ReconcilerDecision(
            action="eligible",
            issue_number=event.issue_number,
            pr_number=event.pr_number,
            phase="fix_conflict",
            reason=f"PR #{event.pr_number} has a merge conflict",
        )
    if event.unresolved_threads > 0:
        return ReconcilerDecision(
            action="eligible",
            issue_number=event.issue_number,
            pr_number=event.pr_number,
            phase="address_comments",
            reason=f"PR #{event.pr_number} has {event.unresolved_threads} unresolved thread(s)",
        )
    if event.failed_ci > 0:
        return ReconcilerDecision(
            action="eligible",
            issue_number=event.issue_number,
            pr_number=event.pr_number,
            phase="fix_ci",
            reason=f"PR #{event.pr_number} has failing CI checks",
        )
    if event.pending_ci > 0:
        return ReconcilerDecision(
            action="skip",
            issue_number=event.issue_number,
            pr_number=event.pr_number,
            phase="wait_ci",
            reason=f"PR #{event.pr_number} CI is still pending; waiting...",
        )
    if event.review_requests > 0 and event.reviews == 0:
        return ReconcilerDecision(
            action="skip",
            issue_number=event.issue_number,
            pr_number=event.pr_number,
            phase="wait_review",
            reason=f"PR #{event.pr_number} is waiting for review",
        )
    if event.review_requests == 0 and event.reviews == 0:
        return ReconcilerDecision(
            action="eligible",
            issue_number=event.issue_number,
            pr_number=event.pr_number,
            phase="request_review",
            reason=f"PR #{event.pr_number} has no review requests or reviews",
        )
    return ReconcilerDecision(
        action="eligible",
        issue_number=event.issue_number,
        pr_number=event.pr_number,
        phase="grade_gate",
        reason=f"PR #{event.pr_number} is ready for gate evaluation",
    )


def handle_event(event: ReconcilerEvent) -> ReconcilerDecision:
    """Route an event to the appropriate pure handler."""
    if event.event_type == "issue_comment":
        return handle_issue_comment(event)
    if event.event_type in (
        "pull_request_review_comment",
        "check_suite",
        "check_run",
        "status",
        "pull_request_review",
        "pull_request",
    ):
        return handle_pr_reconcile(event)
    return ReconcilerDecision(
        action="ignore",
        issue_number=event.issue_number,
        reason=f"unhandled event_type {event.event_type}",
    )


def parse_webhook_event(event_type: str, payload: dict[str, Any]) -> ReconcilerEvent:
    """Parse a real GitHub Actions / Webhook JSON payload into a ReconcilerEvent."""
    if event_type == "issue_comment":
        iss = payload.get("issue", {})
        comment = payload.get("comment", {})
        author = comment.get("user", {}) or comment.get("author", {})
        login = author.get("login", "")
        user_type = author.get("type", "")
        is_bot = (
            user_type == "Bot"
            or login.endswith("[bot]")
            or login in ("github-actions", "agent-session")
        )
        return ReconcilerEvent(
            event_type="issue_comment",
            issue_number=str(iss.get("number", "")),
            author_login=login,
            is_bot=is_bot,
            timestamp=comment.get("created_at", ""),
            raw_payload=payload,
        )

    if event_type in ("pull_request_review_comment", "pull_request_review", "pull_request"):
        pr = payload.get("pull_request", {})
        issue_num = str(payload.get("issue_number") or pr.get("issue_number") or pr.get("number", ""))
        pr_num = str(pr.get("number", ""))
        unresolved = payload.get("unresolved_threads", 0)
        req_rev = len(pr.get("requested_reviewers", [])) if isinstance(pr.get("requested_reviewers"), list) else payload.get("review_requests", 0)
        reviews = payload.get("reviews", 0)
        return ReconcilerEvent(
            event_type=event_type,
            issue_number=issue_num,
            pr_number=pr_num,
            unresolved_threads=unresolved,
            review_requests=req_rev,
            reviews=reviews,
            raw_payload=payload,
        )

    if event_type in ("check_suite", "check_run", "status"):
        pr = payload.get("pull_request", {})
        issue_num = str(payload.get("issue_number") or pr.get("issue_number") or pr.get("number", ""))
        pr_num = str(pr.get("number", ""))
        failed = payload.get("failed_ci", 0)
        pending = payload.get("pending_ci", 0)
        return ReconcilerEvent(
            event_type=event_type,
            issue_number=issue_num,
            pr_number=pr_num,
            failed_ci=failed,
            pending_ci=pending,
            raw_payload=payload,
        )

    return ReconcilerEvent(event_type=event_type, issue_number="", raw_payload=payload)


class PollingAdapter:
    """Adapter that synthesizes ReconcilerEvent structs from observed GitHub state.

    Allows the polling host (local driver pass) to feed synthesized events into the
    exact same pure handlers that a webhook host drives.
    """

    @staticmethod
    def synthesize_comment_event(
        issue_number: str,
        comments: list[dict[str, Any]],
    ) -> ReconcilerEvent | None:
        if not comments:
            return None
        latest = comments[-1]
        author = latest.get("author", {}) or latest.get("user", {})
        login = author.get("login", "")
        is_bot = (
            not login
            or login.endswith("[bot]")
            or login in ("github-actions", "agent-session")
        )
        return ReconcilerEvent(
            event_type="issue_comment",
            issue_number=str(issue_number),
            author_login=login,
            is_bot=is_bot,
            timestamp=latest.get("createdAt", "") or latest.get("created_at", ""),
        )

    @staticmethod
    def synthesize_pr_event(
        issue_number: str,
        pr_number: str,
        pr_details: dict[str, Any],
    ) -> ReconcilerEvent:
        has_conflict = False
        merge_state_status = pr_details.get("merge_state_status")
        mergeable = pr_details.get("mergeable")
        if merge_state_status == "DIRTY" or mergeable == "CONFLICTING":
            has_conflict = True

        return ReconcilerEvent(
            event_type="pull_request",
            issue_number=str(issue_number),
            pr_number=str(pr_number),
            unresolved_threads=pr_details.get("unresolved", 0),
            failed_ci=pr_details.get("failed_ci", 0),
            pending_ci=pr_details.get("pending_ci", 0),
            review_requests=pr_details.get("req_rev", 0),
            reviews=pr_details.get("revd", 0),
            has_conflict=has_conflict,
        )


def run_webhook_reconciler(
    event_type: str,
    payload: dict[str, Any],
    host_provides_lock: bool = True,
) -> dict[str, Any]:
    """Runner path for webhook-driven events.

    Mutual exclusion:
    When host_provides_lock=True (e.g. GHA workflow concurrency group), git ref lock
    acquisition is bypassed completely.
    """
    evt = parse_webhook_event(event_type, payload)
    decision = handle_event(evt)
    res = {
        "event": evt,
        "decision": decision,
        "acquired_git_lock": False,
    }
    if not host_provides_lock and decision.action == "eligible":
        res["acquired_git_lock"] = True
    return res
