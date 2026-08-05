#!/usr/bin/env python3
"""Classify normalized project-board state without external side effects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TextIO
import sys

Severity = Literal["FAIL", "WARN"]


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


def main() -> int:
    """Placeholder command entry point; collection is added in the next phase."""
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
