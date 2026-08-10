#!/usr/bin/env python3
"""Shim re-exporting agent_sessions.driver.writes."""

import sys
from pathlib import Path

src_path = str(Path(__file__).resolve().parent.parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from agent_sessions.driver.writes import *  # noqa: F401, F403
from agent_sessions.driver.writes import (  # noqa: F401
    DEFAULT_BASE,
    EXAMPLES,
    KINDS,
    PROTECTED_BRANCHES,
    ManifestError,
)
