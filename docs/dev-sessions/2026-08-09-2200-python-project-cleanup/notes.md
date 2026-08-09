# Refactor: Standard Python Package Layout & Tooling

## Overview
Refactored `agent-sessions` into a standard, modern Python package using a `src/` layout (`src/agent_sessions/`), `hatchling` build system, `ruff` linter/formatter, and `mypy` type checking while maintaining full backwards compatibility with all existing CLI entry points, Makefile targets, and GHA runners.

## Key Changes
1. **Package Architecture (`src/agent_sessions/`)**:
   - `src/agent_sessions/driver/`: Modularized driver components (`agent_session_driver.py`, `gate.py`, `gh_query.py`, `agent_runner.py`, `discussion_manager.py`).
   - `src/agent_sessions/scripts/`: Modularized utility scripts (`label_manager.py`, `board_audit.py`, `commit_lint.py`, `docs_check.py`, `guard_lint.py`, `assertion_lint.py`, `run_progress.py`, `run_swarm.py`, `session_artifact_stats.py`, `validate_tdd.py`).
   - Standard package exports and `pyproject.toml` hatchling configuration.

2. **Shim Compatibility**:
   - Retained thin wrapper shims in `driver/*.py` and `scripts/*.py` delegating to `agent_sessions.*` so direct invocations (like `python3 driver/gate.py` and `python3 -I -S -c "import gate"`) continue to function without requiring site-packages or breaking existing contracts.

3. **Tooling & Quality Guards**:
   - Configured `ruff` for linting and formatting.
   - Configured `mypy` for strict type checking across all 18 source files.
   - Added `make lint` and `make typecheck` targets to `Makefile` and wired them into `make check`.

4. **Test Suite Verification**:
   - Updated tests to import directly from `agent_sessions.*`.
   - Verified that all 252 tests pass in ~8 seconds via `make check`.
