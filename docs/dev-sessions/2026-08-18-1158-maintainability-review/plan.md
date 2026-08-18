# Safety-First Maintainability Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task by task. Steps use
> checkbox syntax for tracking.

**Goal:** Restore the Claude permission contract lost in the Python conversion,
make its verifier exercise the launched command, correct the governance boundary,
and file the deferred maintainability work.

**Architecture:** `agent_runner` will own safe Claude defaults because it constructs
the process boundary. The coordinator may add restrictions, but it cannot remove
mandatory denials. Documentation will describe the current Python runtime without
changing the project's conservative allowlist.

**Tech stack:** Python 3.11+, pytest, argparse, subprocess, GNU Make, Markdown, GitHub
CLI.

**Spec:** `docs/dev-sessions/2026-08-18-1158-maintainability-review/spec.md`

## Global constraints

- Work only in the `refactor/maintainability-review` worktree.
- Preserve all public Make targets and the shell compatibility launcher.
- Do not edit `skills/**`.
- Do not broaden the risk-path allowlist.
- Keep the runtime repair specific to the Claude backend.
- Treat follow-up issue filing as an external write authorized by Les; do not edit
  existing issue bodies.

---

## Task 1: Restore and prove the Claude permission policy

This slice makes safe policy the runner's default and replaces the inert shell-comment
check with an assertion over the real Claude argv.

**Files:**

- Modify: `driver/test_agent_runner.py` — capture the launched command and add the
  failing permission-policy cases.
- Modify: `src/agent_sessions/driver/agent_runner.py` — define and compose the Claude
  allow/deny policy at the process boundary.
- Modify: `Makefile` — make `skill-readonly` run the command-level regression tests.
- Modify: `driver/agent-session-driver.sh` — remove the sentinel permission comment.

**Interfaces:**

- Produce: `DEFAULT_ALLOWED_TOOLS: tuple[str, ...]`.
- Produce: `BASE_DENIED_TOOLS: tuple[str, ...]`.
- Produce: `mandatory_disallowed_tools(skill_dir: Path) -> tuple[str, ...]`.
- Produce: `compose_disallowed_tools(skill_dir: Path, additional: str = "") -> str`.
- Preserve: `run_agent(argv: list[str] | None = None) -> int`.

- [x] **Step 1: Add command-capture test support and failing regression tests.** —
  `run_and_capture` now returns the real subprocess argv/environment, and both
  policy regressions were added.

  Refactor the existing mocked `Popen` setup into a helper that returns both the
  launched argv and child environment. Add tests with these assertions:

  ```python
  def option_value(command: list[str], name: str) -> str:
      return command[command.index(name) + 1]


  def test_claude_command_restores_mandatory_permission_policy(tmp_path, monkeypatch):
      command, _ = run_and_capture(tmp_path, monkeypatch)
      allowed = option_value(command, "--allowedTools")
      denied = option_value(command, "--disallowedTools")

      assert allowed
      assert "Bash(*)" in allowed.split(",")
      assert "Bash(gh pr merge:*)" in denied.split(",")
      assert f"Edit(/{tmp_path.resolve()}/**)" in denied.split(",")
      assert f"Write(/{tmp_path.resolve()}/**)" in denied.split(",")
      assert f"NotebookEdit(/{tmp_path.resolve()}/**)" in denied.split(",")


  def test_caller_rules_cannot_replace_mandatory_denials(tmp_path, monkeypatch):
      command, _ = run_and_capture(
          tmp_path,
          monkeypatch,
          extra_argv=("--allowed-tools", "Read", "--disallowed-tools", "Bash(rm:*)"),
      )
      assert option_value(command, "--allowedTools") == "Read"
      denied = option_value(command, "--disallowedTools").split(",")
      assert "Bash(rm:*)" in denied
      assert "Bash(gh pr merge:*)" in denied
      assert f"Edit(/{tmp_path.resolve()}/**)" in denied
  ```

- [x] **Step 2: Run the named tests and observe the intended failure.** — The
  named selection failed twice with the expected empty/default-replacement
  assertions (exit 1) before production edits.

  Run:

  ```text
  uv run pytest -q \
    driver/test_agent_runner.py::test_claude_command_restores_mandatory_permission_policy \
    driver/test_agent_runner.py::test_caller_rules_cannot_replace_mandatory_denials
  ```

  Expected before implementation: both tests fail because the captured allowed and
  denied values are empty or contain only the caller's rule.

- [x] **Step 3: Implement safe Claude policy composition.** — The Claude branch
  now supplies default allowed tools and composes immutable mandatory denials
  ahead of caller additions.

  Add the former Bash policy as immutable tuples and compose mandatory rules with
  caller additions:

  ```python
  DEFAULT_ALLOWED_TOOLS = (
      "Read", "Write", "Edit", "Glob", "Grep", "Task", "TodoWrite",
      "BashOutput", "KillShell", "NotebookEdit", "Bash(*)",
  )

  BASE_DENIED_TOOLS = (
      "Bash(gh pr merge:*)",
      "Bash(gh pr merge *)",
      "Bash(git push --force:*)",
      "Bash(gh repo delete:*)",
  )

  def mandatory_disallowed_tools(skill_dir: Path) -> tuple[str, ...]:
      return BASE_DENIED_TOOLS + tuple(
          f"{tool}(/{skill_dir}/**)" for tool in ("Edit", "Write", "NotebookEdit")
      )

  def compose_disallowed_tools(skill_dir: Path, additional: str = "") -> str:
      rules = [*mandatory_disallowed_tools(skill_dir)]
      rules.extend(rule for rule in additional.split(",") if rule)
      return ",".join(rules)
  ```

  In the Claude command, use `args.allowed_tools` when supplied; otherwise join
  `DEFAULT_ALLOWED_TOOLS`. Always call `compose_disallowed_tools(skill_dir,
  args.disallowed_tools)`.

- [x] **Step 4: Run focused tests and the agent-runner suite.** —
  `uv run pytest -q driver/test_agent_runner.py` reported 13 passes.

  Run:

  ```text
  uv run pytest -q driver/test_agent_runner.py
  ```

  Expected: all agent-runner tests pass, including both command-policy tests.

- [x] **Step 5: Replace the source-text Make target.** — `skill-readonly` runs
  the two command-boundary tests, and the shell sentinel comment is gone.

  Change `skill-readonly` to run the two named pytest cases. Keep it independent so
  downstream criteria may still cite `make skill-readonly`. Remove the sentinel
  `DENIED_TOOLS` comment from the shell launcher.

- [x] **Step 6: Verify the independently callable target.** —
  `make skill-readonly` reported two pytest passes.

  Run:

  ```text
  make skill-readonly
  ```

  Expected: pytest runs both command-policy cases and reports two passes. Confirm the
  output comes from pytest rather than a grep success message.

- [x] **Step 7: Run the full project gate.** — `make check` reported 484
  passes plus Ruff and mypy success; `docs-check` explicitly skipped its nested
  assertion-count check and is not recorded as verified coverage.

  Run:

  ```text
  make check
  ```

  Expected: the complete suite, Ruff, mypy, and repository detectors pass. Record any
  existing `docs-check` skip without treating it as verified coverage.

- [x] **Step 8: Manual review.** — Independent review confirmed the required
  double-slash path form, caller narrowing/additive denial behavior, and an
  unchanged OpenCode command; task quality approved with no findings.

  Inspect the captured-rule expectations and confirm:

  - the resolved skill path produces Claude's required double-slash absolute form;
  - caller-supplied allowed tools may narrow the default;
  - caller-supplied denied tools only add restrictions;
  - the OpenCode command remains unchanged.

- [x] **Step 9: Commit the runtime repair.** — Commit `a9def56` (`fix: restore
  mandatory agent permission rules`) contains exactly the four planned files.

  Stage only the four phase files and commit:

  ```text
  fix: restore mandatory agent permission rules
  ```

---

## Task 2: Retarget governance and architecture documentation

This doc-only slice identifies the Python oracle and routing paths, describes the
current package boundary, and preserves the conservative default for unlisted paths.
TDD does not apply because this phase changes historical and architectural prose.

**Files:**

- Modify: `AGENTS.md` — retarget gated paths and correct the drivable-test rationale.
- Modify: `docs/design.md` — describe the Python harness and mark the former language
  split as superseded.
- Modify: `docs/orientation.md` — correct the runtime layout and write-manifest scope.

**Interfaces:** None. This phase changes governance and explanatory prose only.

- [x] **Step 1: Update the risk partition without widening it.** — `AGENTS.md`
  now names the package oracle/coordinator, keeps the compatibility launcher
  gated, and explicitly leaves every unlisted `src/**` path at `needs-review`.

  In `AGENTS.md`:

  - name `src/agent_sessions/driver/gate.py` as the gate oracle;
  - name `src/agent_sessions/driver/agent_session_driver.py` as outcome routing;
  - describe `driver/agent-session-driver.sh` as a compatibility launcher that remains
    gated pending an explicit reclassification;
  - describe `driver/test_*.py` as the drivable harness tests;
  - state that unlisted `src/**` paths remain `needs-review` under the default.

- [x] **Step 2: Update the durable architecture docs.** — `docs/design.md` and
  `docs/orientation.md` now describe the Python runtime, state ownership, and
  validated write-manifest categories while retaining superseded history.

  In `docs/design.md` and `docs/orientation.md`:

  - describe the harness as Python with a thin Bash compatibility launcher;
  - point orchestration, parsing, routing, and write validation at their current
    package modules;
  - mark the 2026-07-29 Bash/Python language split as historical and superseded by
    the 2026-08-09 conversion;
  - distinguish GitHub-native queue state from local run provenance, locks, and
    recovery artifacts;
  - list the validated write-manifest categories instead of saying the driver writes
    only labels and board fields.

- [x] **Step 3: Run targeted stale-claim scans.** — The scan found no obsolete
  current-state path or language-split claim; remaining short-path matches are
  explicitly dated and superseded.

  Run:

  ```text
  rg -n "driver/gate.py|agent-session-driver.sh:485|bash, plus a Python parser|bash for orchestration" \
    AGENTS.md docs/design.md docs/orientation.md
  ```

  Expected: no current-state claim uses the removed Python paths or the former
  language split. Historical passages may retain the old path only when they name a
  dated event and say it is superseded.

- [x] **Step 4: Verify documentation and the full gate.** — `make docs-check`
  passed with its disclosed assertion-count skip; `make check` reported 484
  passes plus Ruff, mypy, and detector success.

  Run:

  ```text
  make docs-check
  make check
  ```

  Expected: both commands pass. Record the files inspected by `docs-check`; do not
  convert its assertion-count skip into a pass.

- [x] **Step 5: Manual review.** — Independent review approved the task with
  no findings and confirmed the default-deny partition, historical framing,
  and absence of live-state restatements.

  Read the edited sections in sequence and confirm that they:

  - preserve the default-deny allowlist;
  - distinguish the compatibility launcher from the shipping coordinator;
  - avoid restating live counts or board state;
  - preserve dated reasoning as history rather than silently deleting it.

- [x] **Step 6: Commit the governance correction.** — Commit `2ec7916`
  (`docs: describe the Python driver boundaries`) contains exactly the three
  planned documentation files.

  Stage the three documentation files and commit:

  ```text
  docs: describe the Python driver boundaries
  ```

---

## Task 3: File and record deferred maintainability work

This slice turns the review findings outside the approved code scope into durable,
focused backlog items. It changes no runtime behavior. TDD does not apply to issue
filing; each proposed check must still name a runnable mechanism or state honestly
that human judgment is required.

**Files:**

- Create: `docs/dev-sessions/2026-08-18-1158-maintainability-review/followups.md` —
  frozen issue titles, bodies, overlap notes, and resulting URLs.
- Create: `docs/dev-sessions/2026-08-18-1158-maintainability-review/followup-coordinator-decomposition.md`
  — body for "Refactor: decompose driver main into lifecycle operations".
- Create: `docs/dev-sessions/2026-08-18-1158-maintainability-review/followup-github-adapters.md`
  — body for "Refactor: consolidate GitHub I/O behind explicit adapters".
- Create: `docs/dev-sessions/2026-08-18-1158-maintainability-review/followup-driver-check.md`
  — body for "Verifier: make driver-check inspect the shipping Python boundaries".
- Create: `docs/dev-sessions/2026-08-18-1158-maintainability-review/followup-docs-check-parallel.md`
  — body for "Fix: prevent docs-check assertion verification from skipping under make check".
- Create: `docs/dev-sessions/2026-08-18-1158-maintainability-review/followup-backend-permissions.md`
  — body for "Safety: define permission parity for non-Claude agent backends".
- Modify: `docs/dev-sessions/2026-08-18-1158-maintainability-review/notes.md` — final
  review findings, issue URLs, verification, and handoff.

**Interfaces:** GitHub issues in `lmorchard/agent-sessions`; no issue or PR body is
edited after creation in this phase.

- [x] **Step 1: Draft focused follow-up issues.** — Five frozen bodies record
  goals, evidence, bounded scope, checks or human judgment, tier rationale,
  and overlap with #152/#195; the stale gate docstring is owned by #248.

  Write one section per issue in `followups.md`, with goal, evidence, bounded scope,
  runnable checks or an explicit human-judgment criterion, tier, and overlap notes.
  Draft these topics:

  1. Decompose `agent_session_driver.main()` into testable lifecycle operations and
     typed run context.
  2. Consolidate direct GitHub and board I/O behind explicit adapters, preserving
     error provenance.
  3. Replace the shell-only `driver-check` with a verifier over the shipping Python
     execution and write boundaries.
  4. Prevent `docs-check` assertion verification from skipping inside parallel
     `make check`.
  5. Define and enforce permission parity for non-Claude backends before treating
     them as equivalent hosts.

  Reference issue #152 for policy separation and issue #195 for distribution; do
  not duplicate either question.

- [x] **Step 2: Validate issue drafts against the live backlog.** — Two live
  backlog reads found no issue owning any of the five concrete topics; #3,
  #152, and #195 were recorded as neighboring but non-duplicate scopes.

  Run:

  ```text
  gh issue list --repo lmorchard/agent-sessions --state open --limit 200 \
    --json number,title,body,labels
  ```

  Expected: no open issue already owns one of the five concrete topics. If a match
  exists, replace the new draft with an overlap note and do not file a duplicate.

- [x] **Step 3: File each non-duplicate issue from its body file.** — Created
  issues #246, #247, #248, #249, and #250 from the frozen body files after
  confirming `gh` authentication as `lmorchard`.

  Save the approved sections in the five body files named above, then run these
  commands:

  ```text
  gh issue create --repo lmorchard/agent-sessions \
    --title "Refactor: decompose driver main into lifecycle operations" \
    --body-file docs/dev-sessions/2026-08-18-1158-maintainability-review/followup-coordinator-decomposition.md
  gh issue create --repo lmorchard/agent-sessions \
    --title "Refactor: consolidate GitHub I/O behind explicit adapters" \
    --body-file docs/dev-sessions/2026-08-18-1158-maintainability-review/followup-github-adapters.md
  gh issue create --repo lmorchard/agent-sessions \
    --title "Verifier: make driver-check inspect the shipping Python boundaries" \
    --body-file docs/dev-sessions/2026-08-18-1158-maintainability-review/followup-driver-check.md
  gh issue create --repo lmorchard/agent-sessions \
    --title "Fix: prevent docs-check assertion verification from skipping under make check" \
    --body-file docs/dev-sessions/2026-08-18-1158-maintainability-review/followup-docs-check-parallel.md
  gh issue create --repo lmorchard/agent-sessions \
    --title "Safety: define permission parity for non-Claude agent backends" \
    --body-file docs/dev-sessions/2026-08-18-1158-maintainability-review/followup-backend-permissions.md
  ```

  Record each returned URL in `followups.md` and `notes.md`. Do not add board fields
  or labels unless the issue body derives a tier and the matching label already
  exists.

- [x] **Step 4: Verify the filed issues.** — `gh issue view` comparisons found
  all five remote titles and bodies byte-for-byte equal to their frozen local
  drafts, with no closing keyword, label, or project-item mutation.

  For each returned issue URL, run:

  ```text
  gh issue view "$issue_url" --repo lmorchard/agent-sessions --json title,body,url
  ```

  Compare the title and body with the frozen draft. Confirm no closing keyword was
  introduced into a commit message or issue body accidentally.

- [x] **Step 5: Complete session notes and run final verification.** — Notes
  contain commits, URLs, OpenCode and detector boundaries, plus the #249
  errata; `make check` reported 484 passes and all other gates successful,
  with the known assertion-count skip disclosed.

  Record implementation commits, follow-up URLs, the unresolved OpenCode boundary,
  and the observed `docs-check` behavior in `notes.md`. Then run:

  ```text
  make check
  git diff --check origin/main...HEAD
  git status --short
  ```

  Expected: project checks pass; the committed diff has no whitespace errors; only
  intentional session-note edits remain before the final documentation commit.

- [x] **Step 6: Commit the review record.** — Commit `a1c5f55` recorded the
  five issues and session findings; review-driven commit `3d2d670` corrected
  #249's immutable local record, and scoped re-review approved both errata.

  Stage only the session follow-up records and updated notes, then commit:

  ```text
  docs: record maintainability review follow-ups
  ```

---

## Final branch review and fix wave

The broad branch review found safety gaps outside the original file list. The spec's
safety objective controlled the resolution; the SDD ledger records the two scope
rulings and their cost if wrong.

- [x] **Run the broad whole-branch review.** — Review of `origin/main..d9695d2`
  found one critical, four important, and one minor issue; the branch was not
  considered ready before fixes.
- [x] **Reconcile both live governance inputs.** — `AGENTS.md` and `CLAUDE.md`
  now carry the same complete risk-policy section, and `docs-check` compares that
  parsed section mechanically.
- [x] **Prove the governance guard can fail.** — Two tests failed before the
  checker existed; GREEN tests cover harmless text outside the policy and a
  controlled drivable-path divergence.
- [x] **Enforce allowed-tool narrowing.** — A caller may request an ordered subset
  of the Claude default allowlist; an unsupported tool returns exit 2 before
  `Popen`. The widening regression failed before implementation and passed after.
- [x] **Strengthen command-policy coverage.** — Tests require exactly one allow
  and deny option and compare the complete ordered allowlist, all four destructive
  denials, all three skill-path denials, and caller additions.
- [x] **Correct remaining boundary prose.** — Governance and orientation now
  distinguish shipping detector modules, drivable root tests, agent-requested
  manifest writes, coordinator-owned operational writes, and #248's launcher-only
  verifier gap; adjacent Make/assertion-lint text is current.
- [x] **Verify and review the fix wave.** — Commit `e97cff6` (`fix: close
  maintainability review findings`) passed `make check` with 487 tests, Ruff,
  mypy, and all guards. The single scoped re-review marked all six findings
  addressed with no new breakage.
