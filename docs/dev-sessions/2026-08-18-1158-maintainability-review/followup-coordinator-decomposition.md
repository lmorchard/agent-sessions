## Goal

Break `agent_session_driver.main()` into named lifecycle operations backed by a typed
run context, without changing the CLI or the driver's observable routing behavior.

## Evidence

`src/agent_sessions/driver/agent_session_driver.py:1042-1869` currently resolves
configuration and credentials, reads GitHub state, selects and locks work, creates a
workspace, invokes an agent, applies requested writes, classifies the result, persists
records, and reports the outcome in one function. Existing modules already supply
bounded seams for routing, gate classification, workspace management, backend
execution, and write-manifest validation.

The current shape makes each lifecycle boundary difficult to test without arranging a
complete `main()` run. It also leaves transient values and resolved configuration in a
large local-variable set rather than an explicit contract.

## Bounded scope

- Introduce a typed context for resolved configuration, credentials, paths, and
  per-run state. Keep raw CLI parsing separate from resolved state.
- Extract lifecycle operations for preflight, queue snapshot and selection, workspace
  preparation, invocation, classification and persistence, and final reporting.
- Preserve the current CLI, compatibility launcher, routing rules, state-file formats,
  write-manifest boundary, and console output unless an existing test requires a
  documented correction.
- Do not redesign `router.py`, `gate.py`, `writes.py`, or backend commands in this issue.

## Acceptance criteria

- **C1 — human judgment.** A reviewer SHALL confirm that the extracted operations
  correspond to lifecycle boundaries rather than arbitrary line-count slices, and that
  the typed context does not become a catch-all object with unrelated mutable state.
- **C2 — runnable.** Existing full-loop and workspace integration tests SHALL pass
  unchanged:

  ```text
  uv run pytest -q driver/test_full_loop.py driver/test_driver.py driver/test_workspace_driver_integration.py
  ```

- **C3 — runnable.** New unit tests SHALL call at least the preflight, selection, and
  classify-and-record operations without invoking the whole CLI. The check is:

  ```text
  uv run pytest -q driver/test_driver.py
  ```

- **G1 — runnable.** The complete project gate SHALL remain green:

  ```text
  make check
  ```

## Tier

`needs-review`. The work edits
`src/agent_sessions/driver/agent_session_driver.py`, the protected outcome-routing
surface, and C1 requires architectural judgment.

## Overlap

Issue #152 asks how policy should be separated from code. This issue does not choose a
policy format or move policy into configuration; it only creates internal lifecycle
boundaries in the coordinator. Issue #195 asks how the harness is distributed to a
second repository and remains separate.
