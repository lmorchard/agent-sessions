# Notes

Session started from `origin/main` at `6f62a98` in the
`refactor/maintainability-review` worktree. Baseline `make check` passed before
implementation.

## Implementation record

- `a9def56` (`fix: restore mandatory agent permission rules`) restored the Claude
  permission floor at the process boundary and replaced the source-text
  `skill-readonly` check with command-capture tests.
- `2ec7916` (`docs: describe the Python driver boundaries`) retargeted the risk
  partition and architecture docs to the shipping Python modules.
- `e97cff6` (`fix: close maintainability review findings`) synchronized the live
  AGENTS/CLAUDE risk policy, added a mechanical parity guard, enforced allowed-tool
  narrowing, completed the command-policy assertions, and corrected the remaining
  boundary prose.

Task 3 filed the deferred work without editing existing issues, adding labels, or
changing project-board fields:

- https://github.com/lmorchard/agent-sessions/issues/246 — decompose the coordinator
  into lifecycle operations.
- https://github.com/lmorchard/agent-sessions/issues/247 — consolidate GitHub I/O
  behind explicit adapters.
- https://github.com/lmorchard/agent-sessions/issues/248 — make `driver-check` inspect
  the shipping Python boundaries.
- https://github.com/lmorchard/agent-sessions/issues/249 — stop assertion-count
  verification from skipping under `make check`.
- https://github.com/lmorchard/agent-sessions/issues/250 — define permission parity
  for non-Claude backends.

Each issue was fetched after creation and its title, body, and URL matched the frozen
local draft exactly. The live backlog comparison found no duplicate. Issue #152 remains
the policy-separation owner, issue #195 remains the distribution owner, and issue #3
remains the GHA-host owner.

## Review findings carried forward

- OpenCode still runs with `--auto` and consumes none of Claude's mandatory allow and
  deny rules. The driver supplies both backends the read-scoped GitHub environment, but
  no evidence establishes equivalent local file or command containment. Issue #250
  records the required threat-model decision and fail-closed behavior.
- `src/agent_sessions/driver/gate.py` retains a present-tense Bash-orchestration
  docstring from before the 2026-08-09 conversion. That protected oracle path was
  outside Task 2. Issue #248 owns the correction alongside the shipping-boundary
  verifier; a separate issue would duplicate its scope.
- The planned parallel-only `docs-check` finding was too narrow. Both `make check` and
  standalone `make docs-check` skip assertion-count verification. The helper passes
  literal pytest glob arguments without shell expansion; the equivalent direct command
  exits 4 with `file or directory not found`. Issue #249 records both the standalone
  defect and the requirement that the fix remain reliable under parallel execution.

### Post-filing erratum for #249

Review round 1 found two errors in the immutable issue body:

- The body says the relevant implementation paths are drivable. `make docs-check`
  invokes `agent_sessions.scripts.docs_check`, implemented at
  `src/agent_sessions/scripts/docs_check.py`. Because the risk partition classifies
  every unlisted `src/**` path as `needs-review`, #249 is gated by the implementation
  path as well as its missing discriminating oracle. The derived tier remains correct.
- The final overlap sentence says the issue is limited to the parallel skip. #249
  covers the standalone collection defect plus reliable verification under parallel
  `make check`, as the rest of the body states.

The frozen body file and GitHub issue were not changed. `followups.md` carries the same
erratum next to the filed URL.

## Final branch review

The broad review stopped the branch on two load-bearing omissions: `CLAUDE.md` was a
second live governance input left stale by the original plan, and caller-supplied
Claude allowlists could widen rather than only narrow the default. It also found that
the behavioral verifier omitted three destructive-command denials, plus several stale
path and write-boundary claims.

The final fix wave resolved all six findings. `docs-check` now compares the complete
`Risk-gated paths` section in `AGENTS.md` and `CLAUDE.md`; a controlled divergence test
proves the guard's polarity. The Claude runner rejects unsupported allowed tools before
launch, and its command-boundary tests compare the complete effective allow/deny
policy. The scoped re-review approved every finding with no new breakage.

## Handoff

The session records contain the exact issue bodies and URLs. No push, merge, or
deployment was performed. The isolated branch and worktree remain available for Les's
review.

## Final verification

- The final fix-wave `make check` passed: `driver-check`, governance parity,
  assertion and commit linters, Ruff, mypy, permission-policy tests, and 487 pytest
  cases completed successfully. `docs-check`
  still reported its assertion-count skip; this is the known defect recorded in #249,
  not verified count coverage.
- `git diff --check origin/main...HEAD` passed for the committed branch diff.
- `git diff --check` passed for the Task 3 records before staging.
- The pre-commit status contained only the controller-managed `plan.md` modification and
  the six new follow-up records plus this updated `notes.md`.
