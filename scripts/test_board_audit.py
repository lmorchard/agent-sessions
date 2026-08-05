"""Tests for the pure board-audit classification and reporting API."""

import io
import json
import os
import subprocess
import sys
from types import SimpleNamespace
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


def test_parse_board_items_keeps_target_issues_and_ignores_drafts_and_other_repositories():
    records = [
        {
            "title": "Target issue",
            "status": "Ready",
            "content": {"type": "Issue", "number": 17, "repository": "acme/widgets"},
        },
        {"content": {"type": "DraftIssue"}},
        {"content": {"type": "Issue", "repository": "other/widgets"}},
    ]

    assert board_audit.parse_board_items(records, "acme/widgets") == [
        board_audit.BoardItem(17, "Target issue", "Ready"),
    ]


@pytest.mark.parametrize(
    "record, context",
    [
        ({}, "content"),
        ({"content": None}, "content"),
        ({"content": {"type": "Issue"}}, "repository"),
        ({"content": {"type": "Issue", "repository": "acme/widgets"}}, "number"),
        (
            {"content": {"type": "Issue", "repository": "acme/widgets", "number": 1}},
            "title",
        ),
        (
            {
                "title": "Bad status",
                "status": 1,
                "content": {"type": "Issue", "repository": "acme/widgets", "number": 1},
            },
            "status",
        ),
    ],
)
def test_parse_board_items_rejects_missing_or_invalid_target_fields(record, context):
    with pytest.raises(board_audit.AuditError, match=context):
        board_audit.parse_board_items([record], "acme/widgets")


def test_parse_board_items_normalizes_omitted_status_to_none():
    assert board_audit.parse_board_items([
        {
            "title": "No project status",
            "content": {"type": "Issue", "repository": "acme/widgets", "number": 1},
        },
    ], "acme/widgets") == [board_audit.BoardItem(1, "No project status", None)]


def test_parse_board_items_accepts_an_explicit_null_status():
    assert board_audit.parse_board_items([
        {
            "title": "No project status",
            "status": None,
            "content": {"type": "Issue", "repository": "acme/widgets", "number": 1},
        },
    ], "acme/widgets") == [board_audit.BoardItem(1, "No project status", None)]


@pytest.mark.parametrize(
    "records, context",
    [
        ([], "Status"),
        ([{"name": "Status", "options": [{"name": "In review"}]}], "Done"),
        ([{"name": "Status", "options": [{"name": "Done"}]}], "In review"),
    ],
)
def test_parse_status_field_requires_status_done_and_in_review(records, context):
    with pytest.raises(board_audit.AuditError, match=context):
        board_audit.parse_status_field(records)


def test_parse_status_field_accepts_required_options():
    board_audit.parse_status_field([
        {"name": "Status", "options": [{"name": "Ready"}, {"name": "Done"}, {"name": "In review"}]},
    ])


def test_parse_issues_accepts_valid_records():
    assert board_audit.parse_issues([
        {"number": 17, "title": "A real issue", "state": "OPEN"},
        {"number": 18, "title": "A closed issue", "state": "CLOSED"},
    ]) == {
        17: board_audit.Issue(17, "A real issue", "OPEN"),
        18: board_audit.Issue(18, "A closed issue", "CLOSED"),
    }


@pytest.mark.parametrize(
    "record, context",
    [
        ({"title": "Missing", "state": "OPEN"}, "number"),
        ({"number": 1, "state": "OPEN"}, "title"),
        ({"number": 1, "title": "Unknown", "state": "MERGED"}, "state"),
    ],
)
def test_parse_issues_rejects_invalid_records(record, context):
    with pytest.raises(board_audit.AuditError, match=context):
        board_audit.parse_issues([record])


def test_parse_closing_issue_numbers_extracts_references():
    assert board_audit.parse_closing_issue_numbers([
        {"number": 31, "closingIssuesReferences": [{"number": 17}, {"number": 18}]},
        {"number": 32, "closingIssuesReferences": []},
    ]) == {17, 18}


@pytest.mark.parametrize(
    "record, context",
    [
        ({"closingIssuesReferences": []}, "number"),
        ({"number": 31, "closingIssuesReferences": None}, "closingIssuesReferences"),
        ({"number": 31, "closingIssuesReferences": [{}]}, "number"),
    ],
)
def test_parse_closing_issue_numbers_rejects_invalid_records(record, context):
    with pytest.raises(board_audit.AuditError, match=context):
        board_audit.parse_closing_issue_numbers([record])


def test_run_gh_returns_decoded_json_from_the_gh_subprocess(monkeypatch):
    seen: list[object] = []

    def fake_run(*args, **kwargs):
        seen.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout='[{"number": 1}]', stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    assert board_audit.run_gh(["issue", "list"], "issues") == [{"number": 1}]
    assert seen == [
        ((["gh", "issue", "list"],), {"capture_output": True, "text": True, "check": False}),
    ]


def test_run_gh_preserves_query_label_and_stderr_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=2, stdout="[]", stderr="not authenticated\n"),
    )

    with pytest.raises(board_audit.AuditError, match="issues query failed: not authenticated"):
        board_audit.run_gh(["issue", "list"], "issues")


def test_run_gh_translates_os_errors_to_labeled_audit_errors(monkeypatch):
    def missing_gh(*args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "gh")

    monkeypatch.setattr("subprocess.run", missing_gh)

    with pytest.raises(board_audit.AuditError, match=r"issues query failed: \[Errno 2\]"):
        board_audit.run_gh(["issue", "list"], "issues")


def test_run_gh_rejects_malformed_json(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="not json", stderr=""),
    )

    with pytest.raises(board_audit.AuditError, match="items query returned malformed JSON"):
        board_audit.run_gh(["project", "item-list"], "items")


def test_bounded_records_accepts_raw_arrays_and_project_named_arrays():
    assert board_audit.bounded_records([{"number": 1}], "issues", 2) == [{"number": 1}]
    assert board_audit.bounded_records(
        {"items": [{"number": 1}], "totalCount": 1}, "items", 2, "items",
    ) == [{"number": 1}]


@pytest.mark.parametrize(
    "payload, key, context",
    [
        ({}, None, "array"),
        ({}, "items", "items"),
        ({"items": [1]}, "items", "object"),
        ({"items": [], "totalCount": "1"}, "items", "totalCount"),
        ({"items": [], "totalCount": 1}, "items", "totalCount"),
    ],
)
def test_bounded_records_rejects_invalid_shapes_and_incomplete_project_payloads(payload, key, context):
    with pytest.raises(board_audit.AuditError, match=context):
        board_audit.bounded_records(payload, "items", 2, key)


@pytest.mark.parametrize("limit", [1, 2, 100, 500])
def test_bounded_records_rejects_a_response_at_its_limit(limit):
    with pytest.raises(board_audit.AuditError, match="potentially truncated"):
        board_audit.bounded_records([{}] * limit, "records", limit)


def configure_gh_stub(tmp_path, monkeypatch, responses, failure=None):
    response_paths = {}
    for name, response in responses.items():
        path = tmp_path / f"{name}.json"
        path.write_text(response if isinstance(response, str) else json.dumps(response))
        response_paths[name] = path

    stub = tmp_path / "gh"
    stub.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

queries = {
    ("project", "field-list"): ("field", ["project", "field-list", "9", "--owner", "acme", "--format", "json", "--limit", "100"]),
    ("project", "item-list"): ("item", ["project", "item-list", "9", "--owner", "acme", "--format", "json", "--limit", "500"]),
    ("issue", "list"): ("issue", ["issue", "list", "--repo", "acme/widgets", "--state", "all", "--limit", "500", "--json", "number,title,state"]),
    ("pr", "list"): ("pr", ["pr", "list", "--repo", "acme/widgets", "--state", "open", "--limit", "500", "--json", "number,closingIssuesReferences"]),
}

argv = sys.argv[1:]
entry = queries.get(tuple(argv[:2]))
if entry is None or argv != entry[1]:
    sys.stderr.write("unexpected gh argv: " + json.dumps(argv))
    raise SystemExit(97)
name, _ = entry
with Path(os.environ["BOARD_AUDIT_GH_LOG"]).open("a") as log:
    log.write(json.dumps(argv) + "\\n")
if os.environ.get("BOARD_AUDIT_GH_FAILURE") == name:
    sys.stderr.write("stubbed " + name + " failure\\n")
    raise SystemExit(2)
print(Path(os.environ["BOARD_AUDIT_" + name.upper() + "_RESPONSE"]).read_text())
""",
    )
    stub.chmod(0o755)
    log_path = tmp_path / "gh.jsonl"
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("BOARD_AUDIT_GH_LOG", str(log_path))
    for name, path in response_paths.items():
        monkeypatch.setenv(f"BOARD_AUDIT_{name.upper()}_RESPONSE", str(path))
    if failure is not None:
        monkeypatch.setenv("BOARD_AUDIT_GH_FAILURE", failure)
    return log_path


def default_gh_responses(status="In review"):
    return {
        "field": {"fields": [{"name": "Status", "options": [{"name": "Done"}, {"name": "In review"}]}], "totalCount": 1},
        "item": {"items": [{"title": "Issue title", "status": status, "content": {"type": "Issue", "number": 17, "repository": "acme/widgets"}}], "totalCount": 1},
        "issue": [{"number": 17, "title": "Issue title", "state": "OPEN"}],
        "pr": [],
    }


def run_cli():
    return subprocess.run(
        [sys.executable, "scripts/board_audit.py", "--owner", "acme", "--project", "9", "--repo", "acme/widgets"],
        capture_output=True,
        text=True,
        check=False,
    )


def expected_gh_calls():
    return [
        ["project", "field-list", "9", "--owner", "acme", "--format", "json", "--limit", "100"],
        ["project", "item-list", "9", "--owner", "acme", "--format", "json", "--limit", "500"],
        ["issue", "list", "--repo", "acme/widgets", "--state", "all", "--limit", "500", "--json", "number,title,state"],
        ["pr", "list", "--repo", "acme/widgets", "--state", "open", "--limit", "500", "--json", "number,closingIssuesReferences"],
    ]


def test_cli_uses_only_the_four_bounded_queries_and_reports_warnings(tmp_path, monkeypatch):
    log_path = configure_gh_stub(tmp_path, monkeypatch, default_gh_responses())

    completed = run_cli()

    assert completed.returncode == 0
    assert completed.stdout == (
        "WARN #17: is 'In review' without an open pull request that closes it\n"
        "board-audit: scanned 1 issue item(s); 0 failure(s); 1 warning(s)\n"
    )
    assert [json.loads(line) for line in log_path.read_text().splitlines()] == expected_gh_calls()


def test_cli_reports_a_clean_result(tmp_path, monkeypatch):
    configure_gh_stub(tmp_path, monkeypatch, default_gh_responses(status="Ready"))

    completed = run_cli()

    assert completed.returncode == 0
    assert completed.stdout == "board-audit: scanned 1 issue item(s); 0 failure(s); 0 warning(s)\n"


def test_cli_returns_one_for_strict_audit_failures(tmp_path, monkeypatch):
    configure_gh_stub(tmp_path, monkeypatch, default_gh_responses(status="Done"))

    completed = run_cli()

    assert completed.returncode == 1
    assert completed.stdout == (
        "FAIL #17: is open but project status is 'Done'\n"
        "board-audit: scanned 1 issue item(s); 1 failure(s); 0 warning(s)\n"
    )


@pytest.mark.parametrize(
    "responses, failure, expected",
    [
        ({**default_gh_responses(), "issue": "not json"}, None, "FAIL: issues query returned malformed JSON: Expecting value"),
        (default_gh_responses(), "item", "FAIL: board items query failed: stubbed item failure"),
    ],
)
def test_cli_reports_operational_failures_as_zero_scanned(tmp_path, monkeypatch, responses, failure, expected):
    configure_gh_stub(tmp_path, monkeypatch, responses, failure=failure)

    completed = run_cli()

    assert completed.returncode == 1
    assert completed.stdout == f"{expected}\nboard-audit: scanned 0 issue item(s); 1 failure(s); 0 warning(s)\n"


def test_cli_allows_an_empty_target_repository_item_set(tmp_path, monkeypatch):
    responses = default_gh_responses()
    responses["item"] = {"items": [{"content": {"type": "DraftIssue"}}], "totalCount": 1}
    log_path = configure_gh_stub(tmp_path, monkeypatch, responses)

    completed = run_cli()

    assert completed.returncode == 0
    assert completed.stdout == "board-audit: scanned 0 issue item(s); 0 failure(s); 0 warning(s)\n"
    assert [json.loads(line) for line in log_path.read_text().splitlines()] == expected_gh_calls()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--owner", "acme", "--project", "0", "--repo", "acme/widgets"],
        ["--owner", "acme", "--project", "9", "--repo", "acme"],
        ["--owner", "acme", "--project", "9", "--repo", "acme/widgets/extra"],
    ],
)
def test_cli_rejects_invalid_project_and_repository_arguments(arguments):
    completed = subprocess.run(
        [sys.executable, "scripts/board_audit.py", *arguments],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "error:" in completed.stderr


def test_make_board_audit_binds_this_repository():
    completed = subprocess.run(
        ["make", "-n", "board-audit"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        check=True,
    )

    assert completed.stdout.split() == [
        "python3", "scripts/board_audit.py",
        "--owner", "lmorchard", "--project", "9",
        "--repo", "lmorchard/agent-sessions",
    ]
