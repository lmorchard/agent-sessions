#!/usr/bin/env bash
#
# agent-session board-driver wrapper (Python implementation)
#
set -euo pipefail

# DENIED_TOOLS: ,Edit(/$SKILL_DIR/**), ,Write(/$SKILL_DIR/**), ,NotebookEdit(/$SKILL_DIR/**)

export PYTHONPATH="${PYTHONPATH:-}:$(dirname "$0")/../src"
exec uv run python -m agent_sessions.driver.agent_session_driver "$@"
