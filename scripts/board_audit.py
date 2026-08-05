#!/usr/bin/env python3
"""Classify normalized project-board state without external side effects."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from typing import Literal, TextIO
import sys

Severity = Literal["FAIL", "WARN"]

FIELD_LIMIT = 100
ITEM_LIMIT = 500
ISSUE_LIMIT = 500
PR_LIMIT = 500


class AuditError(RuntimeError):
    """A GitHub response cannot support a trustworthy audit."""


def require_dict(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AuditError(f"{context} must be an object")
    return value


def require_list(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise AuditError(f"{context} must be an array")
    return value


def require_str(value: object, context: str) -> str:
    if not isinstance(value, str):
        raise AuditError(f"{context} must be a string")
    return value


def require_int(value: object, context: str) -> int:
    if type(value) is not int:
        raise AuditError(f"{context} must be an integer")
    return value


def run_gh(args: list[str], label: str) -> object:
    """Run one read-only GitHub CLI query and decode its JSON response."""
    try:
        completed = subprocess.run(
            ["gh", *args], capture_output=True, text=True, check=False,
        )
    except OSError as error:
        raise AuditError(f"{label} query failed: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise AuditError(f"{label} query failed: {detail}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise AuditError(f"{label} query returned malformed JSON: {error.msg}") from error


def bounded_records(
    payload: object, label: str, limit: int, key: str | None = None,
) -> list[dict[str, object]]:
    """Reject malformed or potentially truncated query result collections."""
    container: dict[str, object] | None = None
    if key is None:
        values = require_list(payload, f"{label} response")
    else:
        container = require_dict(payload, f"{label} response")
        values = require_list(container.get(key), f"{label} response {key}")
    records = [require_dict(value, f"{label} response record {index}") for index, value in enumerate(values)]
    if container is not None and "totalCount" in container:
        total_count = require_int(container["totalCount"], f"{label} response totalCount")
        if total_count > len(records):
            raise AuditError(
                f"{label} response totalCount {total_count} exceeds returned record count {len(records)}",
            )
    if len(records) >= limit:
        raise AuditError(f"{label} response is potentially truncated at limit {limit}")
    return records


@dataclass(frozen=True)
class BoardItem:
    number: int
    title: str
    status: str | None


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    state: str


@dataclass(frozen=True)
class Finding:
    severity: Severity
    issue_number: int | None
    message: str


@dataclass(frozen=True)
class AuditResult:
    scanned: int
    findings: tuple[Finding, ...]


def parse_status_field(records: list[dict[str, object]]) -> None:
    """Require the board's Status field to support audit-relevant states."""
    status_fields = [record for record in records if record.get("name") == "Status"]
    if len(status_fields) != 1:
        raise AuditError("field-list response must contain exactly one Status field")
    options = require_list(status_fields[0].get("options"), "Status field options")
    option_names = {
        require_str(require_dict(option, "Status field option").get("name"), "Status option name")
        for option in options
    }
    for required in ("Done", "In review"):
        if required not in option_names:
            raise AuditError(f"Status field is missing required option {required!r}")


def parse_board_items(records: list[dict[str, object]], repo: str) -> list[BoardItem]:
    """Normalize target-repository issue items from the project response."""
    items: list[BoardItem] = []
    for index, record in enumerate(records):
        context = f"item-list record {index}"
        content = require_dict(record.get("content"), f"{context} content")
        content_type = require_str(content.get("type"), f"{context} content type")
        if content_type == "DraftIssue":
            continue
        if content_type != "Issue":
            raise AuditError(f"{context} has unsupported content type {content_type!r}")
        repository = require_str(content.get("repository"), f"{context} content repository")
        if repository != repo:
            continue
        number = require_int(content.get("number"), f"{context} content number")
        title = require_str(record.get("title"), f"{context} title")
        status = record.get("status")
        if status is not None and not isinstance(status, str):
            raise AuditError(f"{context} status must be a string or null")
        items.append(BoardItem(number, title, status))
    return items


def parse_issues(records: list[dict[str, object]]) -> dict[int, Issue]:
    """Normalize all repository issues consulted by the audit."""
    issues: dict[int, Issue] = {}
    for index, record in enumerate(records):
        context = f"issue-list record {index}"
        number = require_int(record.get("number"), f"{context} number")
        title = require_str(record.get("title"), f"{context} title")
        state = require_str(record.get("state"), f"{context} state")
        if state not in {"OPEN", "CLOSED"}:
            raise AuditError(f"{context} state must be OPEN or CLOSED")
        issues[number] = Issue(number, title, state)
    return issues


def parse_closing_issue_numbers(records: list[dict[str, object]]) -> set[int]:
    """Extract issue numbers closed by open pull requests."""
    closing_numbers: set[int] = set()
    for index, record in enumerate(records):
        context = f"pr-list record {index}"
        require_int(record.get("number"), f"{context} number")
        references = require_list(
            record.get("closingIssuesReferences"), f"{context} closingIssuesReferences",
        )
        for reference_index, reference in enumerate(references):
            reference_context = f"{context} closingIssuesReferences {reference_index}"
            number = require_int(
                require_dict(reference, reference_context).get("number"),
                f"{reference_context} number",
            )
            closing_numbers.add(number)
    return closing_numbers


def collect(owner: str, project: int, repo: str) -> tuple[list[BoardItem], dict[int, Issue], set[int]]:
    """Fetch and normalize the bounded GitHub state required for an audit."""
    field_records = bounded_records(
        run_gh(
            [
                "project", "field-list", str(project), "--owner", owner,
                "--format", "json", "--limit", str(FIELD_LIMIT),
            ],
            "board fields",
        ),
        "board fields",
        FIELD_LIMIT,
        "fields",
    )
    parse_status_field(field_records)
    item_records = bounded_records(
        run_gh(
            [
                "project", "item-list", str(project), "--owner", owner,
                "--format", "json", "--limit", str(ITEM_LIMIT),
            ],
            "board items",
        ),
        "board items",
        ITEM_LIMIT,
        "items",
    )
    issue_records = bounded_records(
        run_gh(
            [
                "issue", "list", "--repo", repo, "--state", "all", "--limit", str(ISSUE_LIMIT),
                "--json", "number,title,state",
            ],
            "issues",
        ),
        "issues",
        ISSUE_LIMIT,
    )
    pr_records = bounded_records(
        run_gh(
            [
                "pr", "list", "--repo", repo, "--state", "open", "--limit", str(PR_LIMIT),
                "--json", "number,closingIssuesReferences",
            ],
            "pull requests",
        ),
        "pull requests",
        PR_LIMIT,
    )
    return (
        parse_board_items(item_records, repo),
        parse_issues(issue_records),
        parse_closing_issue_numbers(pr_records),
    )


def audit(
    items: list[BoardItem],
    issues: dict[int, Issue],
    closing_issue_numbers: set[int],
) -> AuditResult:
    """Apply strict board-state consistency rules to normalized records."""
    findings: list[Finding] = []
    for item in items:
        issue = issues.get(item.number)
        strict_message: str | None = None
        if issue is None:
            strict_message = "is absent from the repository issue query"
        elif item.status is None:
            strict_message = "has no project status"
        elif issue.state == "CLOSED" and item.status != "Done":
            strict_message = f"is closed but project status is {item.status!r}"
        elif issue.state == "OPEN" and item.status == "Done":
            strict_message = "is open but project status is 'Done'"

        if strict_message is not None:
            findings.append(Finding("FAIL", item.number, strict_message))
            continue

        assert issue is not None
        if item.status == "In review" and item.number not in closing_issue_numbers:
            findings.append(Finding(
                "WARN", item.number,
                "is 'In review' without an open pull request that closes it",
            ))
        if item.title != issue.title:
            findings.append(Finding(
                "WARN", item.number,
                f"project title {item.title!r} differs from issue title {issue.title!r}",
            ))

    return AuditResult(len(items), tuple(findings))


def report(result: AuditResult, stream: TextIO = sys.stdout) -> int:
    """Write stable findings and a derived summary; return the audit exit code."""
    failures = 0
    warnings = 0
    for finding in result.findings:
        if finding.severity == "FAIL":
            failures += 1
        else:
            warnings += 1
        issue = f" #{finding.issue_number}" if finding.issue_number is not None else ""
        print(f"{finding.severity}{issue}: {finding.message}", file=stream)

    print(
        "board-audit: "
        f"scanned {result.scanned} issue item(s); "
        f"{failures} failure(s); {warnings} warning(s)",
        file=stream,
    )
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    """Run a read-only project-board consistency audit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--project", required=True, type=int)
    parser.add_argument("--repo", required=True)
    arguments = parser.parse_args(argv)
    if arguments.project <= 0:
        parser.error("--project must be a positive integer")
    if arguments.repo.count("/") != 1 or any(not part for part in arguments.repo.split("/")):
        parser.error("--repo must be in OWNER/REPOSITORY form")
    try:
        items, issues, closing_issue_numbers = collect(
            arguments.owner, arguments.project, arguments.repo,
        )
    except AuditError as error:
        return report(AuditResult(0, (Finding("FAIL", None, str(error)),)))
    return report(audit(items, issues, closing_issue_numbers))


if __name__ == "__main__":
    raise SystemExit(main())
