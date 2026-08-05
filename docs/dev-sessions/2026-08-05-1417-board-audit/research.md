# Board audit research

## Existing detector pattern

- `scripts/docs_check.py:115-234` collects failures and skips separately, prints each result,
  exits 1 on a finding, and reports unavailable evidence as a skip rather than a pass.
- `scripts/assertion_lint.py:69-133` treats zero scanned files as failure, prints each finding,
  and exits 1 when it finds one.
- `scripts/commit_lint.py:235-339` distinguishes an unreadable input range from a clean range;
  both operational errors and findings exit 1.
- `Makefile:30-31` makes the local `check` target an aggregate over repository tests and
  offline detectors. `Makefile:109-139` wires the three Python detectors into that aggregate.
- `Makefile:53-75` runs `driver/test_*.py` and `scripts/test_*.py` by glob. A new
  `scripts/test_*.py` file enters the suite without another Makefile census.
- Detector tests import the shipped module and replace external inputs. See
  `scripts/test_docs_check.py:1-29`, `scripts/test_assertion_lint.py:21-31`, and
  `scripts/test_commit_lint.py:183-245`.

## Existing GitHub data flow

- Issue selection calls `gh issue list --state open --limit 500 --json
  number,title,body,labels` (`driver/agent-session-driver.sh:578-585`). Closed issues never
  reach the driver, and the returned records carry no `state` field.
- Open-PR selection calls `gh pr list --state open --limit 200 --json
  number,title,body,headRefName,url,closingIssuesReferences`
  (`driver/agent-session-driver.sh:512-515`). Selection uses `closingIssuesReferences`;
  post-run discovery uses a separate loose body/title/branch matcher
  (`driver/agent-session-driver.sh:537-555`).
- Board reads call `gh project item-list <number> --owner <owner> --format json --limit 500`
  (`driver/agent-session-driver.sh:563-573`). Runtime code consumes only
  `.items[].content.number` and `.items[].status`; a missing status becomes `no-status`
  (`driver/agent-session-driver.sh:557-560`).
- Board status is advisory. The driver distinguishes only the literal `Ready`; every other
  non-empty value appears as an operator note (`driver/agent-session-driver.sh:647-676`).
- `CLAUDE.md:23-35` declares the current project vocabulary. The driver does not read
  `gh project field-list`; the skill resolves project, field, item, and option IDs when it
  performs transitions (`skills/agent-session/references/github-projects.md:47-109`).
- The current driver does not consume project-item titles, project-item content state, issue
  closed state, PR review decision, or PR merge state.

## Network-isolated test patterns

- The Bash fixture suites place a temporary `gh` executable first on `PATH`, pass fixture
  paths through environment variables, and log argv. The broad reusable pattern is
  `driver/test-park-state.sh:100-152`.
- `driver/test-park-state.sh:320-341` supplies a query-failure fixture whose `gh pr list`
  arm emits stderr and exits 1.
- Newer stubs honor the requested `--json` field list instead of returning a fixed payload.
  See `driver/test-driver.sh:835-859` and `driver/test-driver.sh:1041-1062`. This exposes a
  production query that forgets a required field.
- Python detector tests use `tmp_path` and `monkeypatch`; subprocess tests call the shipped
  entry point. `driver/test_gate.py:203-224` is the smallest CLI example.

## Live board observations on 2026-08-05

Commands used:

```text
gh project field-list 9 --owner lmorchard --format json
gh project item-list 9 --owner lmorchard --limit 200 --format json
gh issue view <number> --repo lmorchard/agent-sessions --json state,...
gh pr list --repo lmorchard/agent-sessions --state open --json ...
```

- Issues #58 and #62 are closed; their project items remain `In review`.
- Issue #71 is closed; its project item has no status.
- Issue #12 is open and `In review`; the repository has no open PR. This needs human judgment.
- Issue #88's project title differs from the issue title. This may be synchronization delay or
  stale project metadata; the API result alone cannot decide.
- The live Status field options are `Backlog`, `Ready`, `In progress`, `In review`, and `Done`.

## Constraints established by the research

- A live board audit requires network access and GitHub authentication. Adding it to
  `make check` would change that target's current offline, credential-free contract.
- Closed-issue/status contradictions are mechanically decidable when the audit fetches issue
  state explicitly. `In review` without an open PR and title drift require warning-level output.
- The script can accept owner, project number, and repository as arguments while the Makefile
  binds this repository's values. Tests can replace the `gh` executable and remain offline.
