# Codebase Research: Issue 150 - Deterministic Workspace Isolation

## Summary of Current Implementation

### 1. Agent Execution & Working Directory Setup (`cwd`)
* Entry point is `agent_sessions.driver.agent_session_driver` (`src/agent_sessions/driver/agent_session_driver.py`).
* `repo_path` is passed via `--repo-path` or resolved from CLI arguments (`src/agent_sessions/driver/agent_session_driver.py:846`).
* When invoking the backend (e.g. `claude`), `agent_runner.run_agent()` receives `args.repo_path` (`src/agent_sessions/driver/agent_runner.py:148`).
* The child process (`claude -p ...`) is spawned with `cwd=str(repo_path)` (`src/agent_sessions/driver/agent_runner.py:148`).
* **Current state:** The agent executes directly inside the root of `repo_path` (the main repository checkout or whatever directory was supplied to `--repo-path`).

### 2. State & Run Directory Management
* Base state directory defaults to `$XDG_STATE_HOME/agent-session/<repo>` (`src/agent_sessions/driver/agent_session_driver.py:894-902`).
* Per-run output artifacts are stored in `state_dir / "runs" / f"{num}-{ts}"` (`src/agent_sessions/driver/agent_session_driver.py:1212-1214`).
* Distributed issue locking uses git remote references `refs/locks/issue-<number>` on `origin` (`src/agent_sessions/driver/agent_session_driver.py:361-480`).
* **Current state:** Git branch checkouts, working trees, or per-issue ephemeral work directories are NOT currently managed by the driver during selection or execution. The driver runs whatever is currently checked out at `repo_path`.

### 3. Credentials & Environment Setup
* Resolved via `credentials.resolve()` (`src/agent_sessions/driver/credentials.py:103-133`): `AGENT_GH_READ_TOKEN` and `DRIVER_GH_WRITE_TOKEN`.
* `credentials.agent_env()` strips write tokens from the agent's environment and passes `AGENT_GH_READ_TOKEN` as `GH_TOKEN`/`GITHUB_TOKEN` (`src/agent_sessions/driver/credentials.py:54-63, 158-175`).
* PreToolUse hook configuration is written to `state_dir / "settings.json"` and passed via `--settings` (`src/agent_sessions/driver/agent_session_driver.py:960-973`).

### 4. Process Execution & Error Handling
* `agent_runner.run_agent()` manages subprocess execution, polling, timeouts (`124`), progress snapshots, and stdout/stderr capture (`src/agent_sessions/driver/agent_runner.py:143-183`).
* Output artifacts (`stream.jsonl`, `stderr.txt`, `parsed.json`, `writes.jsonl`, `gate.yaml`, `runs.jsonl`) are recorded per run (`src/agent_sessions/driver/agent_session_driver.py:1372-1495`).
