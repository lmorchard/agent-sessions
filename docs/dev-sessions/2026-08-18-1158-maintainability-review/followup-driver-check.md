## Goal

Make `make driver-check` inspect the shipping Python execution and write boundaries
instead of checking only the Bash compatibility launcher.

## Evidence

The current target searches `driver/agent-session-driver.sh`, which now only enters the
Python package. Executable GitHub calls and outcome routing live in
`src/agent_sessions/driver/agent_session_driver.py`; the validated write vocabulary
lives in `src/agent_sessions/driver/writes.py`. Existing write tests prove that no
registered manifest kind merges a pull request, but `driver-check` does not cover a
direct merge call added elsewhere in the shipping Python path.

`src/agent_sessions/driver/gate.py` also retains a module docstring that describes Bash
as the live orchestration layer and its Python code as a faithful port. The 2026-08-09
conversion made that current-state description stale. The source path is the protected
gate oracle, so this review recorded the defect rather than editing it inline.

## Bounded scope

- Replace the launcher-only grep with a verifier over shipping Python entry points and
  the registered write-manifest kinds.
- Keep `make driver-check` independently runnable and offline.
- Add mutation-backed coverage showing that a direct merge operation in the
  coordinator or a merge-capable manifest kind makes the target fail.
- Correct `gate.py`'s module docstring so it describes the current Python coordinator,
  keeps the historical extraction rationale as dated history, and removes the live
  Bash/Python split.
- Do not change gate classification, routing behavior, manifest kinds, or the public
  launcher.

## Acceptance criteria

- **C1 — runnable.** `make driver-check` SHALL import or structurally inspect the
  shipping Python boundaries and SHALL pass on the unmodified tree:

  ```text
  make driver-check
  ```

- **C2 — runnable.** Automated mutation tests SHALL prove that `make driver-check`
  fails when a direct pull-request merge command is introduced into the coordinator
  and when a merge-capable write kind is registered. Run:

  ```text
  uv run pytest -q driver/test_writes.py scripts/test_driver_check.py
  ```

- **C3 — human judgment.** A reviewer SHALL confirm that `gate.py`'s module docstring
  distinguishes dated extraction history from the current Python runtime and makes no
  present-tense Bash-orchestration claim.
- **G1 — runnable.** Gate and full-loop behavior SHALL remain unchanged:

  ```text
  uv run pytest -q driver/test_gate.py driver/test_full_loop.py
  make check
  ```

## Tier

`needs-review`. Correcting the stale docstring edits
`src/agent_sessions/driver/gate.py`, the protected oracle, and C3 requires human
judgment. The verifier itself may remain in the drivable `scripts/`, `driver/`, and
`Makefile` paths.

## Overlap

Issue #152 asks where policy belongs; this issue verifies the policy already encoded in
shipping boundaries. Issue #195 asks how project-specific policy is distributed; this
issue does not define that partition.
