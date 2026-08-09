"""Tests for driver/agent_session_driver.py and the Python driver integration."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import agent_session_driver  # noqa: E402


def test_abspath_resolution(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    abs_p = agent_session_driver.abspath("foo/bar")
    assert abs_p == tmp_path / "foo" / "bar"

    abs_existing = agent_session_driver.abspath("/absolute/path")
    assert abs_existing == Path("/absolute/path")


def test_parked_numbers():
    issues = [
        {"number": 1, "labels": [{"name": "agent-session:needs-human"}]},
        {"number": 2, "labels": [{"name": "bug"}]},
        {"number": 3, "labels": [{"name": "agent-session:needs-human-interactive"}]},
    ]
    parked = agent_session_driver.parked_numbers(issues)
    assert parked == {"1", "3"}


def test_build_prompt(tmp_path: Path, monkeypatch):
    class MockResult:
        stdout = json.dumps({
            "title": "Fix bug",
            "body": "Some body content",
            "comments": [{"author": {"login": "alice"}, "body": "Please fix this"}]
        })
        returncode = 0

    def mock_run(cmd, *args, **kwargs):
        return MockResult()

    monkeypatch.setattr("subprocess.run", mock_run)

    prompt = agent_session_driver.build_prompt(42, "owner/repo", "express", tmp_path)
    assert "issue #42: Fix bug" in prompt
    assert "Some body content" in prompt
    assert "@alice: Please fix this" in prompt


def test_driver_cli_help(tmp_path: Path):
    driver_script = Path(__file__).parent / "agent-session-driver.sh"
    res = subprocess.run([str(driver_script), "--help"], capture_output=True, text=True)
    assert res.returncode == 0
    assert "--repo" in res.stdout
