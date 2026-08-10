#!/usr/bin/env bash
#
# agent-session board-driver wrapper (Python implementation)
#
set -euo pipefail

# DENIED_TOOLS: ,Edit(/$SKILL_DIR/**), ,Write(/$SKILL_DIR/**), ,NotebookEdit(/$SKILL_DIR/**)

PYTHON_BIN="${PYTHON_BIN:-python3}"
export PYTHONPATH="${PYTHONPATH:-}:$(dirname "$0")/../src"
exec "$PYTHON_BIN" -m agent_sessions.driver.agent_session_driver "$@"
