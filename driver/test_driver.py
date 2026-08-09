"""Tests for driver/agent_session_driver.py and the Python driver integration."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_sessions.driver import agent_session_driver


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

    prompt = agent_session_driver.build_prompt(42, "express", tmp_path)
    assert "issue #42" in prompt


def test_driver_cli_help(tmp_path: Path):
    driver_script = Path(__file__).parent / "agent-session-driver.sh"
    res = subprocess.run([str(driver_script), "--help"], capture_output=True, text=True)
    assert res.returncode == 0
    assert "--repo" in res.stdout


def test_driver_env_defaults(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "REPO=owner/repo\n"
        "REPO_PATH=/tmp/repo\n"
        "SKILL_DIR=/tmp/skill\n"
        "BOARD=owner/1\n"
        "BACKEND=opencode\n"
        "HIGH_TIER_MODEL=model-high\n"
        "LOW_TIER_MODEL=model-low\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPO", "owner/repo")
    monkeypatch.setenv("REPO_PATH", "/tmp/repo")
    monkeypatch.setenv("SKILL_DIR", "/tmp/skill")
    monkeypatch.setenv("BOARD", "owner/1")
    monkeypatch.setenv("BACKEND", "opencode")
    monkeypatch.setenv("HIGH_TIER_MODEL", "model-high")
    monkeypatch.setenv("LOW_TIER_MODEL", "model-low")

    class MockResult:
        stdout = json.dumps([])
        returncode = 0

    def mock_run(cmd, *args, **kwargs):
        return MockResult()

    monkeypatch.setattr("subprocess.run", mock_run)

    ret = agent_session_driver.main(["--dry-run"])
    assert ret == 0


def test_has_new_human_comment(monkeypatch):
    class MockResult:
        returncode = 0

        def __init__(self, login):
            self.stdout = json.dumps({"comments": [{"author": {"login": login}, "body": "Comment text"}]})

    def mock_run_human(cmd, *args, **kwargs):
        return MockResult("alice")

    monkeypatch.setattr("subprocess.run", mock_run_human)
    has_human, login = agent_session_driver.has_new_human_comment(42, "owner/repo")
    assert has_human is True
    assert login == "alice"

    def mock_run_bot(cmd, *args, **kwargs):
        return MockResult("github-actions[bot]")

    monkeypatch.setattr("subprocess.run", mock_run_bot)
    has_human, login = agent_session_driver.has_new_human_comment(42, "owner/repo")
    assert has_human is False
