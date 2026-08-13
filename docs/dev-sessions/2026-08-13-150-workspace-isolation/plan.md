# Epic 150: Deterministic Per-Issue Workspace Isolation Implementation Plan

**Goal:** Implement strict per-issue workspace isolation using git worktrees to prevent state leakage and git collisions during concurrent driver execution.

**Approach:** Introduce a `workspace.py` module to manage git worktrees at `<state_dir>/workspaces/issue-<number>`. Update `agent_session_driver.py` to route issue runs through isolated workspace paths when invoking agents, performing writes, and executing verification.

**Tech stack:** Python 3 (stdlib `subprocess`, `pathlib`), Git worktrees (`git worktree add/remove`).

---

## Phase 1: Workspace Manager Module (`workspace.py`) and Unit Tests

Create `src/agent_sessions/driver/workspace.py` to handle workspace path derivation, git worktree creation, setup hook execution, and worktree removal.

**Files:**
- Create: `src/agent_sessions/driver/workspace.py`
- Create: `driver/test_workspace.py`

**Key changes:**
- `get_workspace_path(state_dir: Path, issue_number: str | int, workspaces_dir: Path | None = None) -> Path`: returns `(workspaces_dir or state_dir / "workspaces") / f"issue-{issue_number}"`.
- `ensure_workspace(repo_path: Path, workspace_path: Path, branch_name: str, base_ref: str = "origin/main", setup_hook: str | None = None) -> Path`:
  Creates git worktree if `workspace_path` does not exist via `git -C <repo_path> worktree add <workspace_path> -b <branch_name> <base_ref>`, and executes `setup_hook` if provided.
- `remove_workspace(repo_path: Path, workspace_path: Path) -> None`:
  Removes git worktree via `git -C <repo_path> worktree remove --force <workspace_path>` and prunes worktree metadata.

```python
def ensure_workspace(
    repo_path: Path,
    workspace_path: Path,
    branch_name: str,
    base_ref: str = "origin/main",
    setup_hook: str | None = None,
) -> Path:
    repo_path = repo_path.resolve()
    workspace_path = workspace_path.resolve()
    if not workspace_path.exists():
        workspace_path.parent.mkdir(parents=True, exist_ok=True)
        # Check if branch exists
        res = subprocess.run(
            ["git", "-C", str(repo_path), "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
            capture_output=True,
        )
        if res.returncode == 0:
            cmd = ["git", "-C", str(repo_path), "worktree", "add", str(workspace_path), branch_name]
        else:
            cmd = ["git", "-C", str(repo_path), "worktree", "add", "-b", branch_name, str(workspace_path), base_ref]
        subprocess.run(cmd, check=True, capture_output=True, text=True)

        if setup_hook:
            subprocess.run(setup_hook, shell=True, cwd=str(workspace_path), check=True)
    return workspace_path
```

**Verification — automated:**
- [x] `pytest driver/test_workspace.py` passes — **4 passed in 11.01s**
- [x] `make check` passes — **451 passed in 40.42s**

**Verification — manual:**
- [x] Confirm created worktrees are isolated from the main repo checkout — **Verified via test_ensure_workspace_creates_worktree_and_runs_hook**

---

## Phase 2: Driver Integration in `agent_session_driver.py`

Integrate `workspace.py` into `agent_session_driver.py` CLI arguments and execution loop so agent invocations run inside the issue's isolated worktree directory.

**Files:**
- Modify: `src/agent_sessions/driver/agent_session_driver.py` — add `--workspaces-dir`, `--no-workspace-isolation`, `--setup-hook` flags; resolve workspace path for active run; pass workspace `repo_path` to `agent_runner`, prompt builder, and `perform_writes`.
- Create/Modify: `driver/test_workspace_driver_integration.py` — test CLI flags and workspace directory routing during run execution.

**Key changes:**
- CLI arguments: `--workspaces-dir`, `--no-workspace-isolation`, `--setup-hook`.
- In run execution loop (`agent_session_driver.py`):
  ```python
  if not args.no_workspace_isolation:
      ws_dir = Path(args.workspaces_dir).resolve() if args.workspaces_dir else None
      run_repo_path = ensure_workspace(
          repo_path=repo_path,
          workspace_path=get_workspace_path(state_dir, num, ws_dir),
          branch_name=f"issue-{num}",
          setup_hook=args.setup_hook,
      )
  else:
      run_repo_path = repo_path
  ```
- Use `run_repo_path` instead of ambient `repo_path` when building prompt, setting process `cwd`, and executing writes for the issue.

**Verification — automated:**
- [x] `pytest driver/test_workspace_driver_integration.py` passes — **2 passed in 0.41s**
- [x] `make check` passes — **453 passed in 16.73s**

**Verification — manual:**
- [x] Verify `say(f" workspace {run_repo_path}")` is output in run logs during issue execution — **Verified in test output (`cwd .../workspaces/issue-42`)**

---

## Phase 3: Workspace Lifecycle & Cleanup

Add teardown logic to clean up issue worktrees when an issue reaches terminal status (closed / merged) or when explicit workspace pruning is triggered.

**Files:**
- Modify: `src/agent_sessions/driver/workspace.py` — add `cleanup_stale_workspaces()` / `remove_workspace()` helper.
- Modify: `src/agent_sessions/driver/agent_session_driver.py` — invoke workspace removal when an issue finishes or on explicit cleanup request.
- Modify: `driver/test_workspace.py` — add unit tests for workspace removal and pruning.

**Key changes:**
- `remove_workspace(repo_path: Path, workspace_path: Path) -> None`:
  Executes `git -C <repo_path> worktree remove --force <workspace_path>` and `git -C <repo_path> worktree prune`.
- Clean up workspace path after successful PR merge / issue closure or when `--clean-workspaces` CLI flag is passed.

**Verification — automated:**
- [x] `pytest driver/test_workspace.py` passes — **8 passed in 1.74s**
- [x] `make check` passes — **455 passed in 15.57s**

**Verification — manual:**
- [x] Verify worktree directory is cleanly removed after issue cleanup — **Verified via test_driver_clean_workspaces_flag**
