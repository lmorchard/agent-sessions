# Safety-First Maintainability Cleanup Spec

**Goal:** Restore the permission contract lost in the Python conversion, make its
verifier exercise the runtime boundary, and correct the documentation that governs
that boundary before broader refactoring.

**Source:** User request from 2026-08-18

## Current state

The Bash driver became a compatibility launcher, but permission-policy assembly did
not move into the Python execution path. The aggregate check still reports
`skill-readonly` as satisfied because it greps a comment in the launcher. The risk
partition and architecture docs also name the former Bash implementation as the
current oracle and routing surface. See `research.md` for the data flow, history,
and file references.

## Desired end state

1. Every Claude invocation carries the mandatory destructive-command and
   skill-directory deny rules, even when a caller supplies additional rules.
2. A test captures the actual backend command and fails if any mandatory rule is
   absent or malformed.
3. `make skill-readonly` runs the behavioral check instead of inspecting a shell
   comment.
4. The project risk partition names the Python gate and coordinator as gated paths.
5. Core architecture docs describe the Python harness and the validated write
   manifest accurately.
6. Deferred maintainability findings exist as focused GitHub issues, with existing
   issues referenced where they already own part of the problem.

## Design decisions

- **Put mandatory permission policy at the backend execution boundary.**
  `agent_runner` owns the command that crosses into Claude, so it will construct
  the baseline allow list and mandatory deny list from the resolved skill path.
  Caller-supplied deny rules may add restrictions but may not replace the mandatory
  set.
  - **Why:** A coordinator, CLI caller, or future host cannot omit the invariant by
    forgetting an argument.
  - **Rejected:** Recreate the old string assembly in
    `agent_session_driver.main()`. That restores one caller and leaves the runner's
    public entry point unsafe by default.

- **Test the command, not source text.** A mocked `subprocess.Popen` will capture the
  Claude argv. The test will inspect the `--allowedTools` and `--disallowedTools`
  values, including the double-slash absolute-path form Claude requires.
  - **Why:** The current source grep passes on inert content, the project's recorded
    defect class.
  - **Rejected:** Retarget the grep from the launcher to the Python source. A comment
    or unused constant would still satisfy it.

- **Keep the immediate code change narrow.** This session will not split the
  coordinator or move GitHub operations between modules. It will document and file
  those changes as follow-up work.
  - **Why:** The permission regression needs one isolated fix and one discriminating
    verifier before the architecture changes beneath it.
  - **Rejected:** Combine containment repair with an 828-line coordinator
    decomposition. That obscures which change restores the invariant.

- **Retarget governance rather than broaden autonomy.** `AGENTS.md` will gate the
  Python gate and coordinator. The compatibility launcher will remain gated unless
  a later issue proves it safe to add to the drivable allowlist.
  - **Why:** The allowlist defaults unknown paths to `needs-review`; preserving that
    default avoids an accidental permission expansion.

- **Scope the runtime repair to Claude.** OpenCode permission parity will become a
  follow-up issue.
  - **Why:** The current deny-rule mechanism is a Claude CLI contract. This review
    has not established an equivalent OpenCode mechanism.

## Patterns to follow

- Capture backend argv through a mocked `subprocess.Popen`, following
  `driver/test_agent_runner.py:75-128`.
- Build policy from the resolved `skill_dir` beside Claude command construction at
  `src/agent_sessions/driver/agent_runner.py:55-120`.
- Preserve write-manifest defense in depth and its exhaustive registered-kind sweep
  at `driver/test_writes.py:80-99`.
- Keep `make skill-readonly` independently runnable, as documented at
  `Makefile:80-89`, but point it at the behavioral test.

## What we're NOT doing

- Splitting `agent_session_driver.main()`.
- Moving board, PR, CI, or review queries into new clients.
- Introducing typed issue, PR, configuration, or run-record models.
- Reworking broad exception handling.
- Removing the shell compatibility launcher or changing public Make targets.
- Claiming OpenCode has the same permission floor as Claude.
- Fixing the parallel `docs-check` skip in the same change.
- Changing any skill instructions under `skills/**`.

## Open questions

None. Broader findings will be filed as follow-up issues rather than resolved inside
this cleanup.

