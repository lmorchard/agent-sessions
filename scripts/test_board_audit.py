"""Tests for the pure board-audit classification and reporting API."""

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import board_audit  # noqa: E402


@pytest.mark.parametrize(
    "item, issues, expected",
    [
        (
            board_audit.BoardItem(1, "Missing", "Ready"),
            {},
            ("FAIL", 1, "is absent from the repository issue query"),
        ),
        (
            board_audit.BoardItem(2, "No status", None),
            {2: board_audit.Issue(2, "No status", "OPEN")},
            ("FAIL", 2, "has no project status"),
        ),
        (
            board_audit.BoardItem(3, "Closed", "In review"),
            {3: board_audit.Issue(3, "Closed", "CLOSED")},
            ("FAIL", 3, "is closed but project status is 'In review'"),
        ),
        (
            board_audit.BoardItem(4, "Open", "Done"),
            {4: board_audit.Issue(4, "Open", "OPEN")},
            ("FAIL", 4, "is open but project status is 'Done'"),
        ),
    ],
)
def test_strict_rules_report_exact_finding(item, issues, expected):
    result = board_audit.audit([item], issues, set())

    assert result.scanned == 1
    assert [(finding.severity, finding.issue_number, finding.message) for finding in result.findings] == [expected]


@pytest.mark.parametrize(
    "item, issue",
    [
        (board_audit.BoardItem(5, "Closed", "Done"), board_audit.Issue(5, "Closed", "CLOSED")),
        (board_audit.BoardItem(6, "Open", "Ready"), board_audit.Issue(6, "Open", "OPEN")),
    ],
)
def test_clean_state_status_pairs_have_no_strict_finding(item, issue):
    result = board_audit.audit([item], {issue.number: issue}, set())

    assert result.scanned == 1
    assert result.findings == ()


def test_in_review_without_closing_pr_warns():
    item = board_audit.BoardItem(7, "Review", "In review")
    issue = board_audit.Issue(7, "Review", "OPEN")

    result = board_audit.audit([item], {7: issue}, set())

    assert [(finding.severity, finding.issue_number, finding.message) for finding in result.findings] == [
        ("WARN", 7, "is 'In review' without an open pull request that closes it"),
    ]


def test_in_review_with_closing_pr_has_no_pr_warning():
    item = board_audit.BoardItem(8, "Review", "In review")
    issue = board_audit.Issue(8, "Review", "OPEN")

    result = board_audit.audit([item], {8: issue}, {8})

    assert result.findings == ()


def test_title_mismatch_warns():
    item = board_audit.BoardItem(9, "Project title", "Ready")
    issue = board_audit.Issue(9, "Issue title", "OPEN")

    result = board_audit.audit([item], {9: issue}, set())

    assert [(finding.severity, finding.issue_number, finding.message) for finding in result.findings] == [
        ("WARN", 9, "project title 'Project title' differs from issue title 'Issue title'"),
    ]


def test_equal_titles_have_no_title_warning():
    item = board_audit.BoardItem(10, "Same title", "Ready")
    issue = board_audit.Issue(10, "Same title", "OPEN")

    result = board_audit.audit([item], {10: issue}, set())

    assert result.findings == ()


def test_valid_item_can_have_two_warnings_in_stable_order():
    item = board_audit.BoardItem(11, "Project title", "In review")
    issue = board_audit.Issue(11, "Issue title", "OPEN")

    result = board_audit.audit([item], {11: issue}, set())

    assert [(finding.severity, finding.issue_number, finding.message) for finding in result.findings] == [
        ("WARN", 11, "is 'In review' without an open pull request that closes it"),
        ("WARN", 11, "project title 'Project title' differs from issue title 'Issue title'"),
    ]


def test_strict_finding_suppresses_contextual_warnings():
    item = board_audit.BoardItem(12, "Project title", "In review")
    issue = board_audit.Issue(12, "Issue title", "CLOSED")

    result = board_audit.audit([item], {12: issue}, set())

    assert [(finding.severity, finding.issue_number, finding.message) for finding in result.findings] == [
        ("FAIL", 12, "is closed but project status is 'In review'"),
    ]


def test_report_prints_findings_summary_and_failure_exit_code():
    result = board_audit.AuditResult(
        scanned=2,
        findings=(
            board_audit.Finding("FAIL", 58, "is closed but project status is 'In review'"),
            board_audit.Finding("WARN", 12, "is 'In review' without an open pull request that closes it"),
        ),
    )
    stream = io.StringIO()

    exit_code = board_audit.report(result, stream)

    assert stream.getvalue() == (
        "FAIL #58: is closed but project status is 'In review'\n"
        "WARN #12: is 'In review' without an open pull request that closes it\n"
        "board-audit: scanned 2 issue item(s); 1 failure(s); 1 warning(s)\n"
    )
    assert exit_code == 1


@pytest.mark.parametrize(
    "result",
    [
        board_audit.AuditResult(0, ()),
        board_audit.AuditResult(1, (board_audit.Finding("WARN", 3, "warning only"),)),
    ],
)
def test_report_returns_zero_without_failures(result):
    assert board_audit.report(result, io.StringIO()) == 0
