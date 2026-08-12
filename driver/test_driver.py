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
        if [str(c) for c in cmd][:3] == ["gh", "api", "user"]:
            class Login:
                stdout = "agent-session-bot\n"
                returncode = 0
            return Login()
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
    # The driver refuses to start without its own account (#191).
    monkeypatch.setenv("AGENT_GH_READ_TOKEN", "read-token")
    monkeypatch.setenv("DRIVER_GH_WRITE_TOKEN", "write-token")
    monkeypatch.setenv("DRIVER_GH_LOGIN", "agent-session-bot")

    class MockResult:
        stdout = json.dumps([])
        returncode = 0

    def mock_run(cmd, *args, **kwargs):
        if [str(c) for c in cmd][:3] == ["gh", "api", "user"]:
            class Login:
                stdout = "agent-session-bot\n"
                returncode = 0
            return Login()
        return MockResult()

    monkeypatch.setattr("subprocess.run", mock_run)

    ret = agent_session_driver.main(["--dry-run"])
    assert ret == 0


def test_has_new_human_comment(monkeypatch):
    class MockResult:
        returncode = 0

        def __init__(self, login, created_at="2026-08-10T13:00:00Z"):
            self.stdout = json.dumps({"comments": [{"author": {"login": login}, "body": "Comment text", "createdAt": created_at}]})

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

    # Issue 183: Exclude driver identity and extra bot logins
    def mock_run_driver(cmd, *args, **kwargs):
        return MockResult("driver-account")

    monkeypatch.setattr("subprocess.run", mock_run_driver)
    bots = {"driver-account", "extra-bot"}
    has_human, login = agent_session_driver.has_new_human_comment(42, "owner/repo", bot_logins=bots)
    assert has_human is False

    # Issue 183: Filter out comments predating park_time
    def mock_run_predated(cmd, *args, **kwargs):
        return MockResult("alice", created_at="2026-08-10T11:00:00Z")

    monkeypatch.setattr("subprocess.run", mock_run_predated)
    has_human, login = agent_session_driver.has_new_human_comment(42, "owner/repo", park_time="20260810T120000Z")
    assert has_human is False


def test_is_specced():
    # Issue with label agent-session:spec but no body marker
    iss_label = {
        "number": 1,
        "labels": [{"name": "agent-session:spec"}],
        "body": "No marker here",
    }
    assert agent_session_driver.is_specced(iss_label) is True

    # Issue with body marker but no label
    iss_marker = {
        "number": 2,
        "labels": [],
        "body": "<!-- agent-session:spec -->\nSome spec content",
    }
    assert agent_session_driver.is_specced(iss_marker) is True

    # Issue with neither
    iss_neither = {
        "number": 3,
        "labels": [{"name": "bug"}],
        "body": "Plain issue description",
    }
    assert agent_session_driver.is_specced(iss_neither) is False


def test_phase_tiers_coverage():
    expected_phases = {
        "triage",
        "refine",
        "execute",
        "address_comments",
        "fix_ci",
        "request_review",
        "grade_gate",
    }
    assert expected_phases.issubset(agent_session_driver.PHASE_TIERS.keys())
    for phase, tier in agent_session_driver.PHASE_TIERS.items():
        assert tier in ("high", "low")


def test_driver_tier_passed(tmp_path: Path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()

    env_file = tmp_path / ".env"
    env_file.write_text(
        "REPO=owner/repo\n"
        f"REPO_PATH={repo_dir}\n"
        f"SKILL_DIR={skill_dir}\n"
        "BACKEND=opencode\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPO", "owner/repo")
    monkeypatch.setenv("REPO_PATH", str(repo_dir))
    monkeypatch.setenv("SKILL_DIR", str(skill_dir))
    monkeypatch.setenv("BACKEND", "opencode")
    # The driver refuses to start without its own account (#191).
    monkeypatch.setenv("AGENT_GH_READ_TOKEN", "read-token")
    monkeypatch.setenv("DRIVER_GH_WRITE_TOKEN", "write-token")
    monkeypatch.setenv("DRIVER_GH_LOGIN", "agent-session-bot")

    class MockResult:
        stdout = json.dumps([])
        returncode = 0

    def mock_run(cmd, *args, **kwargs):
        if [str(c) for c in cmd][:3] == ["gh", "api", "user"]:
            class Login:
                stdout = "agent-session-bot\n"
                returncode = 0
            return Login()
        return MockResult()

    monkeypatch.setattr("subprocess.run", mock_run)

    captured_args = []

    def mock_run_agent(argv):
        captured_args.append(argv)
        return 0

    monkeypatch.setattr("agent_sessions.driver.agent_runner.run_agent", mock_run_agent)

    # Test execute tier (high)
    ret = agent_session_driver.main(["--issue", "42"])
    assert ret == 0
    assert len(captured_args) == 1
    assert "--tier" in captured_args[0]
    tier_idx = captured_args[0].index("--tier")
    assert captured_args[0][tier_idx + 1] == "high"

    # Test grade_gate tier (low): mock pr_for_issue and check functions
    captured_args.clear()

    def mock_pr_for_issue(num, open_prs):
        return "123\thttps://github.com/owner/repo/pull/123"

    monkeypatch.setattr("agent_sessions.driver.gh_query.pr_for_issue", mock_pr_for_issue)
    monkeypatch.setattr("agent_sessions.driver.agent_session_driver.check_pr_unresolved_threads", lambda r, p: 0)
    monkeypatch.setattr("agent_sessions.driver.agent_session_driver.check_pr_ci_status", lambda r, p: (0, 0))
    monkeypatch.setattr("agent_sessions.driver.agent_session_driver.check_pr_reviews", lambda r, p: (1, 1))

    ret = agent_session_driver.main(["--issue", "42"])
    assert ret == 0
    assert len(captured_args) == 1
    assert "--tier" in captured_args[0]
    tier_idx = captured_args[0].index("--tier")
    assert captured_args[0][tier_idx + 1] == "low"

