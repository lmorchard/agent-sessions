"""Tests for park state and reconciliation logic in driver/agent_session_driver.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import agent_session_driver  # noqa: E402


def test_parked_numbers_filtering():
    issues = [
        {"number": 7, "labels": [{"name": "agent-session:needs-human"}]},
        {"number": 8, "labels": [{"name": "bug"}]},
    ]
    parked = agent_session_driver.parked_numbers(issues)
    assert parked == {"7"}


def test_get_attempts_parsing():
    issues = [
        {"number": 42, "labels": [{"name": "agent-session:attempt-2"}]}
    ]
    attempts = agent_session_driver.get_attempts(42, "stub/repo", issues_json=issues)
    assert attempts == 2
