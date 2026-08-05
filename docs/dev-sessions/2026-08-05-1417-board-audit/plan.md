# Project Board Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox
> (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only Python command that distinguishes strict project-board contradictions
from contextual warnings without making the repository's normal checks depend on GitHub.

**Architecture:** Keep acquisition, normalization, classification, and reporting in one focused
stdlib-only module with explicit interfaces between them. Unit tests exercise the pure audit rules;
stubbed CLI tests exercise the exact `gh` queries and failure modes. A separate Make target binds
the generic command to this repository, after which the current strict findings are reconciled by
explicit operator actions.

**Tech stack:** Python 3.11 standard library, pytest, GNU Make, GitHub CLI.

## Global constraints

- `scripts/board_audit.py` reads GitHub state but never writes it and has no fix mode.
- Strict contradictions exit 1; warnings alone exit 0.
- `make board-audit` is separate from `make check`, CI, and the merge gate.
- Offline tests import the shipped module and replace `gh`; they never require network or auth.
- The audit includes only issue items belonging to `--repo`; draft items and other repositories are
  ignored.
- A failed, malformed, structurally incomplete, or potentially truncated query is a failure, never
  an empty successful audit.
- Do not modify the board driver, the skill, CI configuration, or dependency files.

---

## Task 1: Phase 1 — Pure classification and reporting

Deliver the rule table as a pure, directly imported Python API. This slice can classify normalized
board state and produce the final user-facing severity, summary, and exit code without invoking
GitHub.

**Files:**

- Create: `scripts/board_audit.py` — normalized records, classification, reporting, and an initially
  thin executable entry point.
- Create: `scripts/test_board_audit.py` — table-driven rule, suppression, report, and exit tests.

**Interfaces:**

- Consumes: normalized board items, repository issues, and issue numbers referenced by open PRs.
- Produces:
  - `BoardItem(number: int, title: str, status: str | None)`
  - `Issue(number: int, title: str, state: str)`
  - `Finding(severity: Literal["FAIL", "WARN"], issue_number: int | None, message: str)`
  - `AuditResult(scanned: int, findings: tuple[Finding, ...])`
  - `audit(items, issues, closing_issue_numbers) -> AuditResult`
  - `report(result, stream=sys.stdout) -> int`

**Key changes:**

Use immutable records so tests and later normalization share one unambiguous vocabulary:

```python
from dataclasses import dataclass
from typing import Literal, TextIO

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
```

Apply at most one strict finding per item. Skip both contextual rules when an item has a strict
finding; this prevents a closed `In review` issue from also warning about a missing open PR.

```python
def audit(
    items: list[BoardItem],
    issues: dict[int, Issue],
    closing_issue_numbers: set[int],
) -> AuditResult:
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
```

`report` prints one stable line per finding, then a data-derived summary. It returns 1 if any
finding has severity `FAIL`, otherwise 0.

```text
FAIL #58: is closed but project status is 'In review'
WARN #12: is 'In review' without an open pull request that closes it
board-audit: scanned 2 issue item(s); 1 failure(s); 1 warning(s)
```

- [ ] **Step 1: Add failing tests for every strict rule.** Parametrize missing issue lookup,
  missing status, closed/non-Done, and open/Done. Add controls proving closed/Done and open/non-Done
  are clean. Assert exact severity and issue number, not just result length.
- [ ] **Step 2: Run the focused strict tests and observe the expected import or symbol failure.**
  Run: `uv run --quiet pytest scripts/test_board_audit.py -k 'strict or clean' -v`
  Expected: FAIL because `scripts/board_audit.py` or its public records and `audit` do not exist.
- [ ] **Step 3: Implement the immutable records and the minimum strict classification loop shown
  above.** The pure function consumes the normalized uppercase states that Phase 2 will enforce.
- [ ] **Step 4: Rerun the focused strict tests.**
  Run: `uv run --quiet pytest scripts/test_board_audit.py -k 'strict or clean' -v`
  Expected: PASS.
- [ ] **Step 5: Add failing tests for warning-only behavior and suppression.** Cover `In review`
  with and without a closing open PR, title equality and mismatch, two warnings on one otherwise
  valid item, and a strict item whose potential warnings are both suppressed.
- [ ] **Step 6: Run the warning tests and observe the expected failure.**
  Run: `uv run --quiet pytest scripts/test_board_audit.py -k 'warn or suppress' -v`
  Expected: FAIL because contextual classification is not implemented.
- [ ] **Step 7: Implement the two contextual branches and strict-item `continue` exactly as shown
  above.** Preserve board-item order and warning-rule order so output is stable.
- [ ] **Step 8: Rerun the warning tests.**
  Run: `uv run --quiet pytest scripts/test_board_audit.py -k 'warn or suppress' -v`
  Expected: PASS.
- [ ] **Step 9: Add failing report tests.** With `io.StringIO`, assert the exact finding lines,
  dynamic scanned/failure/warning summary, exit 1 for any failure, and exit 0 for clean or
  warning-only results.
- [ ] **Step 10: Run the report tests and observe the expected missing-function failure.**
  Run: `uv run --quiet pytest scripts/test_board_audit.py -k report -v`
  Expected: FAIL because `report` is not implemented.
- [ ] **Step 11: Implement `report(result: AuditResult, stream: TextIO = sys.stdout) -> int`.** Do
  not use module-level finding accumulators; derive both counts and exit status from `result`.
- [ ] **Step 12: Verify the phase.**
  Run: `uv run --quiet pytest scripts/test_board_audit.py -v`
  Expected: PASS.

**Verification — automated:**

- [ ] `uv run --quiet pytest scripts/test_board_audit.py -v` passes with the phase's rule and
  reporting tests.
- [ ] `make gate-test` passes, proving the new test file is collected by the existing glob.

**Verification — manual:**

- [ ] Read every parametrized case against the classification table in `spec.md`; confirm each row
  has a positive test and the state/status rules have clean controls.
- [ ] Confirm no subprocess or GitHub call is reachable from `audit` or `report`.

- [ ] **Step 13: Commit the phase.**
  Run:
  `git add scripts/board_audit.py scripts/test_board_audit.py && git commit -m "Phase 1: classify board audit findings"`

---

## Task 2: Phase 2 — GitHub acquisition, normalization, and CLI

Turn the pure engine into the generic read-only command from the spec. A field-aware stub
executable supplies all four GitHub responses so tests exercise the shipped subprocess and CLI
paths without network access.

**Files:**

- Modify: `scripts/board_audit.py` — argument parsing, `gh` adapter, response validation,
  normalization, and executable `main`.
- Modify: `scripts/test_board_audit.py` — normalization, operational-failure, query-shape, and
  end-to-end CLI cases.

**Interfaces:**

- Consumes from Phase 1: `BoardItem`, `Issue`, `AuditResult`, `audit`, and `report` with the exact
  signatures defined there.
- Produces:
  - `AuditError(message: str)` for operational and evidence failures.
  - `run_gh(args: list[str], label: str) -> object`
  - `bounded_records(payload: object, label: str, limit: int, key: str | None = None)` returns
    `list[dict[str, object]]`.
  - `parse_status_field(records: list[dict[str, object]]) -> None`
  - `parse_board_items(records: list[dict[str, object]], repo: str) -> list[BoardItem]`
  - `parse_issues(records: list[dict[str, object]]) -> dict[int, Issue]`
  - `parse_closing_issue_numbers(records: list[dict[str, object]]) -> set[int]`
  - `collect(owner: str, project: int, repo: str)` returns
    `tuple[list[BoardItem], dict[int, Issue], set[int]]`.
  - `main(argv: list[str] | None = None) -> int`

**Key changes:**

Set explicit, named limits. The values are policy-free safety bounds, not claims about current
board size:

```python
FIELD_LIMIT = 100
ITEM_LIMIT = 500
ISSUE_LIMIT = 500
PR_LIMIT = 500
```

`run_gh` preserves stderr and query identity on nonzero exit, rejects malformed JSON, and never
turns either case into an empty collection:

```python
class AuditError(RuntimeError):
    pass

def run_gh(args: list[str], label: str) -> object:
    completed = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise AuditError(f"{label} query failed: {detail}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise AuditError(f"{label} query returned malformed JSON: {error.msg}") from error
```

`bounded_records` accepts either the raw arrays returned by issue/PR lists or the named arrays in
Projects payloads. It requires a list of objects. If `totalCount` is present, require an integer and
reject `totalCount > len(records)`. For every command, reject `len(records) >= limit` as potentially
truncated.

The exact four queries are:

```python
["project", "field-list", str(project), "--owner", owner,
 "--format", "json", "--limit", str(FIELD_LIMIT)]
["project", "item-list", str(project), "--owner", owner,
 "--format", "json", "--limit", str(ITEM_LIMIT)]
["issue", "list", "--repo", repo, "--state", "all", "--limit", str(ISSUE_LIMIT),
 "--json", "number,title,state"]
["pr", "list", "--repo", repo, "--state", "open", "--limit", str(PR_LIMIT),
 "--json", "number,closingIssuesReferences"]
```

Normalization rules are structural rather than permissive:

- Require one Status field whose options include exact names `Done` and `In review`.
- Require each project item to contain a `content` object and content `type`.
- Ignore `DraftIssue` content. For `Issue` content, require `repository`; ignore it when the value
  differs from `repo`.
- For a target-repository issue item, require integer `number`, string top-level project `title`,
  and either a string `status` or explicit JSON null.
- Require issue records to contain integer `number` plus string `title` and `state`; accept only
  `OPEN` and `CLOSED` states.
- Require each open PR to contain integer `number` and a list `closingIssuesReferences`; require an
  integer `number` in every referenced issue.

The CLI validates a positive project number and a repository spelling with exactly one `/` and
nonempty owner/name components. On `AuditError`, it reports one operational `FAIL`, a zero-scanned
summary, and exit 1. Otherwise it passes normalized data through Phase 1's `audit` and `report`.

- [ ] **Step 1: Add failing normalization tests.** Cover valid target items, draft exclusion,
  other-repository exclusion, missing/null required fields, missing Status, missing `Done`, missing
  `In review`, valid issue records, unknown issue state, and closing-reference extraction.
- [ ] **Step 2: Run normalization tests and observe the expected missing-symbol failures.**
  Run: `uv run --quiet pytest scripts/test_board_audit.py -k 'parse or status or normalize' -v`
  Expected: FAIL because the parsing functions and `AuditError` do not exist.
- [ ] **Step 3: Implement `AuditError` and the four normalization functions.** Use small helpers
  such as `require_dict`, `require_list`, `require_str`, and `require_int` where they remove repeated
  shape checks; every error message must name its query or record context.
- [ ] **Step 4: Rerun normalization tests.**
  Run: `uv run --quiet pytest scripts/test_board_audit.py -k 'parse or status or normalize' -v`
  Expected: PASS.
- [ ] **Step 5: Add failing adapter tests.** Test nonzero `gh`, useful stderr preservation,
  malformed JSON, wrong top-level shape, missing named arrays, `totalCount` larger than the returned
  Projects array, and arrays whose length reaches each supplied limit.
- [ ] **Step 6: Run adapter tests and observe the expected missing-symbol failures.**
  Run: `uv run --quiet pytest scripts/test_board_audit.py -k 'run_gh or bounded' -v`
  Expected: FAIL because `run_gh` and `bounded_records` do not exist.
- [ ] **Step 7: Implement `run_gh` and `bounded_records` with the exact failure rules above.** Do
  not retry, paginate behind the caller's back, or return a sentinel that can be read as clean.
- [ ] **Step 8: Rerun adapter tests.**
  Run: `uv run --quiet pytest scripts/test_board_audit.py -k 'run_gh or bounded' -v`
  Expected: PASS.
- [ ] **Step 9: Add a failing end-to-end stub test.** Create an executable Python `gh` stub under
  `tmp_path`, prepend it to `PATH`, and have it reject any argv other than the four exact queries
  above. It should read response files from environment variables, log each argv as JSON Lines, and
  emit field, item, issue, or PR JSON based on `sys.argv[1:3]`. Assert all four logged calls and a
  warning-only exit 0 from the shipped `scripts/board_audit.py` subprocess.
- [ ] **Step 10: Run the end-to-end test and observe the expected CLI failure.**
  Run: `uv run --quiet pytest scripts/test_board_audit.py -k 'cli or collect' -v`
  Expected: FAIL because `collect` and the executable CLI are incomplete.
- [ ] **Step 11: Implement `collect`, `argparse` validation, and `main`.** Call the four queries once
  each, in field/item/issue/PR order; normalize; audit; report. Add the standard
  `if __name__ == "__main__": raise SystemExit(main())` entry point.
- [ ] **Step 12: Add CLI controls for a clean result, a strict exit 1, malformed stub output, query
  failure, an empty target-repository item set after four valid responses, and invalid `--repo` /
  nonpositive `--project` arguments. Assert exact severity lines and summaries for command-owned
  failures; the empty target set exits 0 with a zero-scanned summary.
- [ ] **Step 13: Verify the phase.**
  Run: `uv run --quiet pytest scripts/test_board_audit.py -v`
  Expected: PASS.

**Verification — automated:**

- [ ] `uv run --quiet pytest scripts/test_board_audit.py -v` passes.
- [ ] `python3 -I -S -c "import sys; sys.path.insert(0, 'scripts'); import board_audit"` passes,
  proving the command is stdlib-only.
- [ ] `make gate-test` passes with the end-to-end stub isolated from network and credentials.

**Verification — manual:**

- [ ] Inspect the stub's logged argv and confirm all requested JSON fields are consumed by the
  normalizer; no fetched field is decorative and no consumed field is absent.
- [ ] Search `scripts/board_audit.py` for write-capable GitHub verbs (`item-edit`, `item-add`,
  `issue edit`, `pr edit`) and confirm none are present.

- [ ] **Step 14: Commit the phase.**
  Run:
  `git add scripts/board_audit.py scripts/test_board_audit.py && git commit -m "Phase 2: read GitHub state for board audit"`

---

## Task 3: Phase 3 — Repository entry point and live reconciliation

Expose the generic command through the Makefile, demonstrate the detector against the live board,
then perform the three already-approved status corrections as explicit operator writes. The
detector remains read-only throughout.

**Files:**

- Modify: `Makefile` — add discoverable `board-audit` help and target, outside `check`.
- Modify: `scripts/test_board_audit.py` — structural test for the Make target's bound argv.

**Interfaces:**

- Consumes from Phase 2:
  `python3 scripts/board_audit.py --owner lmorchard --project 9 --repo lmorchard/agent-sessions`.
- Produces: `make board-audit`, a repository-specific live audit target that is not a prerequisite
  of `check`.

**Key changes:**

Add the target to `.PHONY` and `help`, but not to the `check:` dependency line:

```make
.PHONY: help check board-audit ...

help:
	@echo "board-audit      audit this repo's live GitHub project (read-only)"

board-audit:
	@python3 scripts/board_audit.py \
		--owner lmorchard --project 9 --repo lmorchard/agent-sessions
```

The wiring test derives the recipe with Make instead of copying the Makefile text:

```python
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
```

- [ ] **Step 1: Add the failing Make wiring test shown above.**
- [ ] **Step 2: Run it and observe the expected failure.**
  Run: `uv run --quiet pytest scripts/test_board_audit.py::test_make_board_audit_binds_this_repository -v`
  Expected: FAIL because `make board-audit` does not exist.
- [ ] **Step 3: Add the `.PHONY`, help, and target lines shown above.** Do not change `check:` or
  any CI file.
- [ ] **Step 4: Rerun the wiring test.**
  Run: `uv run --quiet pytest scripts/test_board_audit.py::test_make_board_audit_binds_this_repository -v`
  Expected: PASS.
- [ ] **Step 5: Run the live detector before any board write.**
  Run: `make board-audit`
  Expected: exit 1. Record every live `FAIL` and `WARN`; verify the strict findings correspond to
  closed #58 / #62 not in `Done` and closed #71 without status before changing anything. If live
  state differs, stop and reconcile the evidence with Les rather than applying the stale write set.
- [ ] **Step 6: Verify GitHub authentication and resolve IDs from fresh reads.** Run
  `gh auth status`, `gh project field-list 9 --owner lmorchard --format json --limit 100`, and
  `gh project item-list 9 --owner lmorchard --format json --limit 500`. Confirm one Status field,
  one `Done` option, and the item IDs for #58, #62, and #71. Do not reuse IDs from session notes.
- [ ] **Step 7: Move only #58, #62, and #71 to `Done`.** For each verified item, run exactly one
  `gh project item-edit --project-id PROJECT_ID --id ITEM_ID --field-id STATUS_FIELD_ID
  --single-select-option-id DONE_OPTION_ID`, substituting only IDs copied from Step 6's fresh
  results. Do not edit issue/PR content, close #12, or change #88's title.
- [ ] **Step 8: Rerun the live detector after the writes.**
  Run: `make board-audit`
  Expected: exit 0 with warning-only output for contextual anomalies still present. Record the
  actual warnings instead of asserting a fixed count.
- [ ] **Step 9: Run full verification.**
  Run: `make check`
  Expected: PASS.

**Verification — automated:**

- [ ] `uv run --quiet pytest scripts/test_board_audit.py -v` passes.
- [ ] `make check` passes; this runs the offline board-audit tests but does not invoke the live
  `board-audit` target.
- [ ] `make board-audit` exits 0 after reconciliation and reports any remaining warnings.

**Verification — manual:**

- [ ] `make help` lists `board-audit` as read-only.
- [ ] Read the `check:` prerequisite line and confirm `board-audit` is absent.
- [ ] Read the final live output and confirm #58, #62, and #71 no longer have strict findings while
  #12 and #88 were not mutated by the detector.

- [ ] **Step 10: Commit the phase.**
  Run:
  `git add Makefile scripts/test_board_audit.py && git commit -m "Phase 3: expose the live board audit"`

---

## Task 4: Final verification and handoff

- [ ] Run `git diff --check origin/main...HEAD` and resolve whitespace errors.
- [ ] Run `make check` and record the fresh suite summaries in `notes.md`.
- [ ] Run `make board-audit` and record the live strict/warning summary in `notes.md` without
  copying volatile counts into maintained project documentation.
- [ ] Run `git status --short`; confirm only intentional session-note changes remain.
- [ ] Review `git diff --stat origin/main...HEAD` and `git diff origin/main...HEAD` for scope drift,
  accidental GitHub writes in the detector, or changes under gated paths.
- [ ] Finish `docs/dev-sessions/2026-08-05-1417-board-audit/notes.md` with decisions, commits,
  verification evidence, external board mutations, and the first check for a cold resume.
- [ ] Commit the completed plan/notes artifact update with an accurate message after verification.
