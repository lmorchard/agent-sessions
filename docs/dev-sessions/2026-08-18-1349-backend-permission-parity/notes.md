# Notes

## 2026-08-18 — design checkpoint

- Issue #250 is In Progress on project 9.
- The branch is isolated in the `issue-250-backend-permission-parity` worktree.
- Baseline `make check` passed before design work.
- Les approved matching and naming Claude's existing native-tool floor for OpenCode.
- Same-user shell access is an accepted residual risk for both backends; OS isolation
  is outside this issue.
- The written spec is awaiting review before implementation planning.

## 2026-08-18 — execution

- Les approved the written spec. The self-reviewed plan was committed before code.
- Phase 1 added the fail-closed OpenCode adapter, runner-owned inline policy,
  `--pure`, supported-version gate, caller-option rejection, and backend-neutral
  `skill-readonly` coverage.
- Phase 2 added a tested live probe and an explicit Make target outside `make check`.
- The Claude live probe passed all three checks.
- OpenCode's host default failed on stale Google reauthentication. The installed
  `opencode/big-pickle` model reached the tools without changing the probe.
- That run exposed a v1.18.18 edit-resource mismatch: OpenCode stripped the leading
  slash before matching `edit`. A model-free debug tool call confirmed the corrected
  dual-path rule, a regression test covered it, and the final live run passed.
- Adversarial review exposed a second precedence seam: target agent-specific
  permissions followed the runner's global denials. Repeating the policy on a fixed
  named agent appeared to close it, but independent review found deeper merge,
  disable/fallback, subagent, and executable custom-tool paths. That intermediate fix
  was not mergeable.
- The corrected boundary disables target project configuration, scrubs inherited
  OpenCode override variables, points both XDG and the separate legacy-home loader at
  a clean per-run root, uses a random agent, sets `disable: false`, denies delegation,
  and resolves one strict absolute executable with a bounded exact-version probe.
- `make opencode-policy-contract` now seeds malicious target config and custom-tool
  fixtures in both the target and an inherited adversarial home. It passed against
  OpenCode 1.18.18, and the final live probe under
  `/tmp/agent-sessions-issue-250/opencode-isolated-proof/` recorded read, edit denial,
  Bash denial, and unchanged-marker evidence as structured fields.
- Raw live artifacts are under `/tmp/agent-sessions-issue-250/` and are intentionally
  untracked. Durable observations are in `research.md` and `docs/findings.md`.
- Focused runner and probe verification passed (29 tests), and `make skill-readonly`
  passed (3 tests).
- Full `make check` passed with 502 tests plus Ruff, mypy, and repository detectors.
  `docs-check` still disclosed the assertion-count verification skip tracked by #249;
  the skip is recorded, not treated as a pass.
- `git diff --check` produced no output.
- After the precedence fix and evidence updates, focused runner/probe verification
  passed (29 tests), `make skill-readonly` passed (3 tests), and the fresh full
  `make check` gate passed with 502 tests plus Ruff, mypy, and repository detectors.
  `docs-check` disclosed the known assertion-count skip tracked by #249; the skip is
  recorded, not treated as a pass.
- Independent final re-review approved the target, XDG, legacy-home, selected-agent,
  delegation, and executable-resolution boundaries with no remaining blocker.
- Final verification passed: 34 focused runner/probe tests, 3 `skill-readonly` tests,
  the model-free OpenCode contract, and `make check` with 507 tests plus Ruff, mypy,
  and repository detectors. `docs-check` disclosed the known assertion-count skip
  tracked by #249; the skip is recorded, not treated as a pass.
- After fetching, `origin/main` is `be59b61`, while this work forked from merged PR
  #251's `6269aac`; that commit is not an ancestor of current main. Branch integration
  needs a history decision before rebase or PR creation.
- Recovery PR #253 restored #251's exact tree on top of #252 and merged as
  `991fc7f`. Its local and CI `make check` gates passed; `git diff` confirmed the
  restoration tree was identical to #251's original squash merge.
- The nine issue #250 commits then rebased cleanly from `6269aac` onto restored
  `origin/main`. The rebased tree was byte-for-byte identical to the independently
  reviewed pre-rebase tree at `e29819b`.
- Post-rebase verification passed: `make check` with 507 tests plus Ruff, mypy, and
  repository detectors, followed by `make opencode-policy-contract`. `docs-check`
  again disclosed the known assertion-count skip tracked by #249; the skip is
  recorded, not treated as a pass.
- The work was squashed to one review commit and opened as PR #254; issue #250 is In
  Review on project 9. The PR body links the approved design artifacts and records
  the shared same-user shell residual risk.
