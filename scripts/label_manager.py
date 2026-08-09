#!/usr/bin/env python3
"""Shim re-exporting agent_sessions.scripts.label_manager."""

import sys
from pathlib import Path

src_path = str(Path(__file__).resolve().parent.parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from agent_sessions.scripts.label_manager import *  # noqa: F401, F403
from agent_sessions.scripts.label_manager import main

if __name__ == "__main__":
    sys.exit(main())
