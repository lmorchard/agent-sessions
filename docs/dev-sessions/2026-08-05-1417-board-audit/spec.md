# Board Audit Spec

**Goal:** Detect contradictions between GitHub issue state and project-board state without
making the repository's offline checks depend on GitHub.

**Source:** User request from 2026-08-05

## Current state

The board driver reads project status only as advisory selection context. It consumes issue
number and status, and it distinguishes only `Ready` from other values
(`research.md`, "Existing GitHub data flow"). It does not compare issue state, project title,
or linked open PR state.

The repository's detectors follow a consistent contract: they import their shipped modules in
tests, distinguish unavailable evidence from a pass, print each finding, and return nonzero on
failure (`research.md`, "Existing detector pattern"). The aggregate `make check` target is
offline and credential-free.

The live board contains three mechanically decidable contradictions: closed issues #58 and #62
remain `In review`, and closed issue #71 has no status. It also contains two contextual anomalies:
open issue #12 is `In review` without an open PR, and #88's project title differs from its issue
title (`research.md`, "Live board observations on 2026-08-05").

## Desired end state

The repository provides `scripts/board_audit.py`, a read-only command that accepts:

```text
--owner <project owner>
--project <project number>
--repo <owner/name>
```

It reads the project's field definitions, project items, all issues in the requested repository,
and open pull requests. It audits only issue items belonging to that repository; it ignores draft
items and items from other repositories.

The command prints one `FAIL` or `WARN` line per finding, followed by a dynamic summary of scanned
issue items, failures, and warnings. It exits 1 for an operational failure or strict contradiction.
It exits 0 when the audit is clean or contains warnings only.

`make board-audit` binds the command to owner `lmorchard`, project `9`, and repository
`lmorchard/agent-sessions`. It remains separate from `make check`. The existing pytest glob runs
the detector's offline tests without GitHub access.

After the detector demonstrates the current strict contradictions, the operator moves #58, #62,
and #71 to `Done`. The operator leaves #12 and #88 unchanged because their warnings require human
judgment.

## Classification contract

| Condition | Result |
|---|---|
| A `gh` query fails, returns malformed JSON, or omits required data | `FAIL`, exit 1 |
| The project lacks a Status field or the `Done` / `In review` values | `FAIL`, exit 1 |
| A target-repository issue item has no status | `FAIL`, exit 1 |
| A project item refers to an issue absent from the complete issue query | `FAIL`, exit 1 |
| A closed issue is not `Done` | `FAIL`, exit 1 |
| An open issue is `Done` | `FAIL`, exit 1 |
| An open issue is `In review` without an open PR that closes it | `WARN`; exit 0 if no failures |
| A project title differs from the issue title | `WARN`; exit 0 if no failures |

The command reports one strict finding per item before contextual warnings, so a closed issue in
`In review` does not also receive a redundant missing-PR warning.

## Design decisions

- **Decision:** Implement the detector in Python over `gh` JSON output.
  - **Why:** The audit joins several typed data sources and must preserve the difference between
    query failure, missing data, and an empty result. Python makes those states explicit and
    continues the repository's incremental split: Bash for orchestration, Python for parsing and
    classification.
  - **Rejected:** Shell plus `jq`, because command substitution and strings collapse the exact null
    states this detector must distinguish. Direct GraphQL was rejected because one-query precision
    does not justify its schema and fixture complexity here.

- **Decision:** Separate data acquisition from classification.
  - **Why:** A pure classification function can consume normalized project, issue, and PR records.
    Tests can cover the rule table without subprocesses; focused CLI tests can cover `gh` failures,
    malformed output, and query shapes.
  - **Rejected:** Mixing subprocess calls into each rule, which would make every rule a networked
    integration test.

- **Decision:** Read the live Status field and verify that `Done` and `In review` exist.
  - **Why:** The field list is authoritative. The detector cannot grade closed or reviewed items if
    those semantic values are unavailable.
  - **Rejected:** Copying the full current option list into the script. The audit needs two semantic
    values, not a second maintained board schema.

- **Decision:** Keep `make board-audit` outside `make check`.
  - **Why:** A live Projects query needs network access and GitHub authentication. `make check`
    currently needs neither and must stay suitable for local work, CI, and forked pull requests.
  - **Rejected:** Treating an unavailable board as a skip inside `make check`; that would weaken an
    offline project gate to accommodate an unrelated network check.

- **Decision:** Report strict contradictions and contextual warnings separately.
  - **Why:** Issue state and `Done` status form a mechanical invariant. Review intent and project
    title synchronization do not. A detector that fails on judgment calls will train operators to
    ignore it.
  - **Rejected:** Failing on every anomaly or reducing every anomaly to a warning.

- **Decision:** Keep reconciliation outside the detector.
  - **Why:** The audit establishes facts; an operator decides and performs writes. A read-only tool
    is safe to run repeatedly and cannot turn a mistaken rule into a bulk board mutation.
  - **Rejected:** `--fix` and automatic reconciliation.

## Components and data flow

1. The CLI validates `--owner`, `--project`, and `--repo`.
2. A `gh` adapter runs four bounded queries:
   - project field definitions;
   - project items;
   - repository issues with both open and closed state;
   - open PRs with `closingIssuesReferences`.
   Each list command uses an explicit limit larger than the current data set. If a response fills
   that limit, the adapter rejects it as potentially truncated instead of auditing partial data.
3. The adapter parses JSON and rejects failed, malformed, truncated, or incomplete responses.
4. A normalization layer selects issue items for the requested repository and constructs lookup
   maps by issue number.
5. A pure audit function applies the classification contract and returns findings plus the number
   of audited issue items.
6. The reporter prints stable `FAIL` / `WARN` lines and a summary, then selects exit status.

## Error handling

- Every `gh` invocation captures stdout and stderr. A nonzero exit names the failed query and
  preserves useful stderr without presenting an empty response as an empty board.
- JSON decoding failures name the query that produced malformed output.
- Missing top-level arrays, required item fields, or issue lookup records are failures, not skips.
- A list response whose length equals its requested limit is a failure because the four `gh` list
  commands do not expose a consistent next-page signal. Raising the limit is safe; silently
  accepting a saturated result is not.
- An empty target-repository item set is reported as a successful scan of zero items only when all
  queries succeeded and their required shapes were present.

## Testing

`scripts/test_board_audit.py` imports the shipped module. Tests cover:

- every row in the classification contract, including controls for the opposite direction;
- suppression of redundant warnings on strict failures;
- repository filtering and exclusion of drafts;
- query failure, malformed JSON, and omitted required fields;
- saturated list responses that might be truncated;
- exact `gh` query arguments, using a field-list-aware stub executable;
- CLI exit 1 for failures and exit 0 for warnings only;
- the summary's audited-item, failure, and warning values.

The implementation follows test-driven development: add a failing focused test, observe the
expected failure, implement the minimum behavior, and rerun the focused test. `make check` is the
final local regression gate; `make board-audit` is the live acceptance check.

## Patterns to follow

- Mirror detector result handling from `scripts/docs_check.py:219-234`: collect findings, print
  them, and make the exit status explicit.
- Import the shipped module and isolate external inputs as in `scripts/test_docs_check.py:1-29`.
- Exercise the executable entry point as in `driver/test_gate.py:203-224`.
- Use field-list-aware `gh` stubs like `driver/test-driver.sh:835-859` so tests catch missing query
  fields.
- Let `Makefile:53-75` discover `scripts/test_board_audit.py` through its existing glob.

## What we're NOT doing

- Adding `board-audit` to `make check`, CI, or the merge gate.
- Writing to GitHub from the detector or adding a `--fix` mode.
- Changing the board driver or moving existing driver logic into Python in this tranche.
- Defining policy profiles for arbitrary project workflows.
- Auditing draft items or items from repositories other than `--repo`.
- Closing #12, changing #88's title, or converting warnings into inferred fixes.
- Adding a general GitHub API client or using GraphQL directly.

## Open questions

None. The design choices needed for planning are resolved above.
