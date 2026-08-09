#!/usr/bin/env bash
#
# agent-session board-driver wrapper (Python implementation)
#
set -euo pipefail

# DENIED_TOOLS: ,Edit(/$SKILL_DIR/**), ,Write(/$SKILL_DIR/**), ,NotebookEdit(/$SKILL_DIR/**)

PYTHON_BIN="${PYTHON_BIN:-python3}"
exec "$PYTHON_BIN" "$(dirname "$0")/agent_session_driver.py" "$@"
