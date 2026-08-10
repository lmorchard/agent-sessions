#!/usr/bin/env python3
"""Tests for the reactive reconciler module (issue #185).

Covers:
  - Criterion 1: Handler pureness (subprocess.run patched to raise, no I/O)
  - Criterion 2: Polling adapter event synthesis
  - Criterion 3: Equivalent decisions between real GHA webhook events and synthesized events
  - Criterion 4: Webhook runner path bypassing git ref locks when host offers mutual exclusion
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from agent_sessions.driver import reconciler


@pytest.fixture(autouse=True)
def disallow_subprocess(monkeypatch):
    """Ensure no handler or parser calls subprocess.run."""
    def _raising_run(*args, **kwargs):
        raise RuntimeError("Direct I/O or subprocess call in reconciler handler is forbidden!")
    monkeypatch.setattr("subprocess.run", _raising_run)


# --- Criterion 1: Pure Handlers --------------------------------------------


def test_handle_issue_comment_human_unparks():
    evt = reconciler.ReconcilerEvent(
        event_type="issue_comment",
        issue_number="42",
        author_login="alice",
        is_bot=False,
    )
    dec = reconciler.handle_issue_comment(evt)
    assert dec.action == "unpark"
    assert dec.issue_number == "42"
    assert dec.author == "alice"
    assert "new comment from @alice" in dec.reason


def test_handle_issue_comment_bot_ignored():
    evt = reconciler.ReconcilerEvent(
        event_type="issue_comment",
        issue_number="42",
        author_login="github-actions[bot]",
        is_bot=True,
    )
    dec = reconciler.handle_issue_comment(evt)
    assert dec.action == "ignore"
    assert dec.issue_number == "42"


def test_handle_pr_reconcile_unresolved_threads():
    evt = reconciler.ReconcilerEvent(
        event_type="pull_request_review_comment",
        issue_number="10",
        pr_number="100",
        unresolved_threads=2,
    )
    dec = reconciler.handle_pr_reconcile(evt)
    assert dec.action == "eligible"
    assert dec.phase == "address_comments"
    assert dec.issue_number == "10"
    assert dec.pr_number == "100"


def test_handle_pr_reconcile_failing_ci():
    evt = reconciler.ReconcilerEvent(
        event_type="check_suite",
        issue_number="11",
        pr_number="101",
        unresolved_threads=0,
        failed_ci=1,
    )
    dec = reconciler.handle_pr_reconcile(evt)
    assert dec.action == "eligible"
    assert dec.phase == "fix_ci"


def test_handle_pr_reconcile_pending_ci_skips():
    evt = reconciler.ReconcilerEvent(
        event_type="check_suite",
        issue_number="12",
        pr_number="102",
        unresolved_threads=0,
        failed_ci=0,
        pending_ci=1,
    )
    dec = reconciler.handle_pr_reconcile(evt)
    assert dec.action == "skip"
    assert dec.phase == "wait_ci"
    assert "CI is still pending" in dec.reason


def test_handle_pr_reconcile_no_reviews_requests_review():
    evt = reconciler.ReconcilerEvent(
        event_type="pull_request_review",
        issue_number="13",
        pr_number="103",
        unresolved_threads=0,
        failed_ci=0,
        pending_ci=0,
        review_requests=0,
        reviews=0,
    )
    dec = reconciler.handle_pr_reconcile(evt)
    assert dec.action == "eligible"
    assert dec.phase == "request_review"


def test_handle_pr_reconcile_reviews_present_grades_gate():
    evt = reconciler.ReconcilerEvent(
        event_type="pull_request_review",
        issue_number="14",
        pr_number="104",
        unresolved_threads=0,
        failed_ci=0,
        pending_ci=0,
        review_requests=0,
        reviews=1,
    )
    dec = reconciler.handle_pr_reconcile(evt)
    assert dec.action == "eligible"
    assert dec.phase == "grade_gate"


# --- Criterion 3: Equivalent Decisions (Webhook vs Synthesized) ----------


@pytest.mark.parametrize(
    "event_type,webhook_payload,synthesized_details,expected_action,expected_phase",
    [
        (
            "issue_comment",
            {
                "issue": {"number": 201},
                "comment": {"user": {"login": "les", "type": "User"}, "created_at": "2026-08-10T12:00:00Z"},
            },
            {"comments": [{"author": {"login": "les"}, "createdAt": "2026-08-10T12:00:00Z"}]},
            "unpark",
            "",
        ),
        (
            "pull_request_review_comment",
            {
                "issue_number": "202",
                "pull_request": {"number": 302},
                "unresolved_threads": 3,
            },
            {"unresolved": 3, "failed_ci": 0, "pending_ci": 0, "req_rev": 0, "revd": 0},
            "eligible",
            "address_comments",
        ),
        (
            "check_suite",
            {
                "issue_number": "203",
                "pull_request": {"number": 303},
                "failed_ci": 1,
            },
            {"unresolved": 0, "failed_ci": 1, "pending_ci": 0, "req_rev": 0, "revd": 0},
            "eligible",
            "fix_ci",
        ),
        (
            "pull_request_review",
            {
                "issue_number": "204",
                "pull_request": {"number": 304},
                "reviews": 1,
            },
            {"unresolved": 0, "failed_ci": 0, "pending_ci": 0, "req_rev": 0, "revd": 1},
            "eligible",
            "grade_gate",
        ),
    ],
)
def test_webhook_and_synthesized_events_reach_identical_decisions(
    event_type,
    webhook_payload,
    synthesized_details,
    expected_action,
    expected_phase,
):
    # Parse real webhook event payload
    webhook_evt = reconciler.parse_webhook_event(event_type, webhook_payload)
    webhook_dec = reconciler.handle_event(webhook_evt)

    # Synthesize event from polling adapter
    if event_type == "issue_comment":
        syn_evt = reconciler.PollingAdapter.synthesize_comment_event("201", synthesized_details["comments"])
    else:
        issue_num = str(webhook_payload.get("issue_number") or webhook_payload.get("pull_request", {}).get("number"))
        pr_num = str(webhook_payload.get("pull_request", {}).get("number"))
        syn_evt = reconciler.PollingAdapter.synthesize_pr_event(issue_num, pr_num, synthesized_details)

    assert syn_evt is not None
    syn_dec = reconciler.handle_event(syn_evt)

    assert webhook_dec.action == syn_dec.action == expected_action
    assert webhook_dec.phase == syn_dec.phase == expected_phase
    assert webhook_dec.issue_number == syn_dec.issue_number


# --- Criterion 4: Webhook Path Bypasses Git Ref Locking -------------------


def test_webhook_reconciler_does_not_acquire_git_lock():
    payload = {
        "issue_number": "301",
        "pull_request": {"number": 401},
        "reviews": 1,
    }
    # When host_provides_lock=True (e.g. GitHub Actions concurrency group)
    res = reconciler.run_webhook_reconciler("pull_request_review", payload, host_provides_lock=True)

    assert res["decision"].action == "eligible"
    assert res["decision"].phase == "grade_gate"
    assert res["acquired_git_lock"] is False
