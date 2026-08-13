# Spec: Epic 150 - Implement Deterministic Per-Issue Workspace Isolation

**Goal:** Provide strict per-issue workspace isolation for agent runs using git worktrees, preventing state leakage and git collisions between concurrent driver runs.

**Source:** Issue #150 (`https://github.com/lmorchard/agent-sessions/issues/150`)

## Current state

* `agent_runner.run_agent()` receives `args.repo_path` (`src/agent_sessions/driver/agent_runner.py:148`) and executes child processes (`claude -p`) with `cwd=str(repo_path)`.
* `agent_session_driver.py` passes the ambient `repo_path` (the root checkout) directly to `run_agent()` (`src/agent_sessions/driver/agent_session_driver.py:1360`).
* Concurrent driver runs operating against the same repo root modify the same working tree, leading to branch switching collisions, uncommitted diff leakage, and git push rejections.

## Desired end state

* For every issue selected by the driver, the driver manages a dedicated, isolated workspace directory at `<state_dir>/workspaces/issue-<number>`.
* The workspace is established as a git worktree (`git worktree add <path> <branch>`) off `origin/main` (or checking out the PR branch if processing an open PR).
* `run_agent()` executes with `cwd = str(workspace_path)`, guaranteeing that file edits, builds, and test runs are isolated to `workspace_path`.
* Workspaces persist across retry attempts for the same issue to preserve intermediate progress until terminal resolution.
* Upon terminal completion or unparking/cleanup, stale issue workspaces are cleanly removed (`git worktree remove --force <path>`).

## Design decisions

- **Decision 1: Use git worktrees under `<state_dir>/workspaces/issue-<number>`**
  - **Why:** Git worktrees share the underlying object store (`.git`), making workspace creation instant and offline, while completely isolating the working files, index, and active branch per issue. Storing them under `state_dir / "workspaces"` keeps them outside the main repository tree.
  - **Rejected:** Full `git clone` per issue (slow, requires network/redundant disk storage) or running directly in the main checkout (causes state leakage and branch collisions across concurrent runs).

- **Decision 2: Persistent workspaces across retries**
  - **Why:** If an agent run times out or fails midway, preserving the workspace allows a retry attempt to inspect existing files or resume without losing progress.
  - **Rejected:** Ephemeral teardown on every retry (destroys work-in-progress on transient timeouts).

- **Decision 3: Lifecycle Hooks (`before_run` and cleanup)**
  - **Why:** After creating or reusing a worktree, project setup (e.g. `uv sync` / `npm install` / `make setup` if configured) ensures the workspace environment is ready before the agent starts.
  - **Rejected:** Relying on the agent to detect missing dependencies or uninstalled virtualenvs manually on every run.

## Patterns to follow

* `agent_runner.py:148` for subprocess `cwd` invocation.
* `credentials.py:158-175` for environment variable scoping and child environment setup.
* `agent_session_driver.py:918-925` for `state_dir` path resolution and directory structure.

## What we're NOT doing

* We are NOT changing the underlying agent models or dispatcher skill logic (`skills/agent-session/`).
* We are NOT modifying the GitHub locking mechanism (`refs/locks/issue-<number>`); workspace isolation works alongside lock acquisition.
* We are NOT adding remote container or VM orchestration (Docker/K8s); isolation is process + git worktree level.

## Open questions & Recommendations

1. **Workspace Location:** Should workspace directories default to `<state_dir>/workspaces/issue-<number>` with an optional `--workspaces-dir` CLI flag?
   - **Recommendation:** Yes. Defaulting to `state_dir / "workspaces"` keeps state contained per repo/driver instance, while `--workspaces-dir` provides flexibility.
2. **Setup Hook:** How should the `before_run` setup hook be determined?
   - **Recommendation:** Auto-detect common baseline setup commands (e.g. `uv sync` if `uv.lock` exists, `npm ci` if `package-lock.json` exists) or allow an optional `--setup-hook` string argument.
3. **Workspace Teardown:** Should workspaces be cleaned up automatically when an issue is merged, closed, or parked?
   - **Recommendation:** Yes, clean up workspace when an issue is closed/merged or when explicit `--clean-workspaces` is requested.
