# Maintainability Review Research

## Repository shape

- `driver/agent-session-driver.sh:1-10` is a compatibility launcher. It adds `src/`
  to `PYTHONPATH` and executes `agent_sessions.driver.agent_session_driver`.
- `src/agent_sessions/driver/agent_session_driver.py:1042-1869` coordinates
  configuration, credentials, selection, workspaces, invocation, classification,
  persistence, and reporting in one `main()` function.
- Pure or bounded modules already provide useful seams:
  `router.select` (`src/agent_sessions/driver/router.py:20-241`), reconciler event
  handling (`src/agent_sessions/driver/reconciler.py:20-280`), GitHub reads
  (`src/agent_sessions/driver/gh_query.py:16-265`), write-manifest validation
  (`src/agent_sessions/driver/writes.py:37-405`), backend execution
  (`src/agent_sessions/driver/agent_runner.py:30-365`), and workspace management
  (`src/agent_sessions/driver/workspace.py:5-104`).
- The coordinator still performs direct GitHub reads and writes beside those
  modules (`agent_session_driver.py:731-987`), including board access, review
  threads, CI, and review state.

## Permission-policy regression

- Before commit `0919300`, the Bash driver assembled a broad allow list and a
  mandatory deny list. It appended `Edit`, `Write`, and `NotebookEdit` rules for
  the resolved skill directory, then passed both lists to `agent_runner`.
  Reproduce with:

  ```text
  git show 0919300^:driver/agent-session-driver.sh | \
    rg -n 'ALLOWED_TOOLS|DENIED_TOOLS|allowed-tools|disallowed-tools'
  ```

- The Python coordinator builds `runner_args` without `--allowed-tools` or
  `--disallowed-tools` (`agent_session_driver.py:1657-1681`).
- `agent_runner.run_agent` still accepts both options, defaults each to an empty
  string, and passes the values to Claude (`agent_runner.py:30-54`, `:81-120`).
- The shell launcher carries the old skill-directory rules only as a comment
  (`driver/agent-session-driver.sh:7`). `make skill-readonly` greps that comment
  (`Makefile:80-89`), so it cannot distinguish the current command from one that
  omits every rule.
- The conversion session specified selection, parking, and aggregate test parity,
  but it did not name permission parity. Inspect with:

  ```text
  git show 0919300:docs/dev-sessions/2026-08-09-170-rewrite-driver/spec.md
  ```

## Verifier and documentation drift

- `make driver-check` searches only the compatibility launcher for merge commands
  (`Makefile:53-59`). The executable write boundary now lives in Python. Existing
  write-manifest tests do reject merge entries and sweep every registered kind
  (`driver/test_writes.py:80-99`).
- The repository risk partition still names `driver/gate.py` and the shell
  launcher as the oracle and routing code (`AGENTS.md:57-81`, `:101-111`). The
  live files are `src/agent_sessions/driver/gate.py` and
  `src/agent_sessions/driver/agent_session_driver.py`.
- `docs/design.md:239-247` and `docs/orientation.md:92-99` still describe the
  harness as Bash plus a Python parser. `docs/design.md:614-623` preserves the
  former Bash/Python split as the current decision.
- `docs/orientation.md:203-205` says the driver writes only labels and board
  fields. The validated manifest also supports issue bodies and comments, issue
  creation, branch pushes, PR creation and edits, and label creation
  (`src/agent_sessions/driver/writes.py:41-69`).

## Baseline verification

From the isolated worktree at commit `6f62a98`:

```text
uv sync --all-groups
make check
```

The suite passed with 482 tests, Ruff, and mypy. During the aggregate run,
`docs-check` printed that assertion-count verification was skipped because it
could not run `make gate-test`; the parallel `gate-test` itself passed. This is a
separate verifier-composition finding, not part of the permission repair.

## Live backlog overlap

- Issue #152 already holds the broad policy-from-code question.
- Issue #195 already holds the distribution and project-policy partition.
- No open issue names the lost mandatory tool rules, coordinator decomposition,
  GitHub-boundary consolidation, or the parallel `docs-check` skip.

