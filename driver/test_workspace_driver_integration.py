import json
import subprocess
from pathlib import Path

import pytest

from agent_sessions.driver import agent_session_driver


@pytest.fixture
def dummy_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "main_repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True)
    (repo / "README.md").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(repo), check=True, capture_output=True)
    return repo


def test_driver_workspace_isolation_enabled(dummy_git_repo: Path, tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    ws_dir = tmp_path / "workspaces"

    # Mock environment
    monkeypatch.setenv("DRIVER_GH_LOGIN", "dummy_bot")
    monkeypatch.setenv("AGENT_GH_READ_TOKEN", "dummy_read_token")
    monkeypatch.setenv("DRIVER_GH_WRITE_TOKEN", "dummy_write_token")

    monkeypatch.setattr("agent_sessions.driver.agent_session_driver.whoami", lambda env: "dummy_bot")

    # Mock router.select
    def mock_select(*args, **kwargs):
        return {
            "messages": [],
            "unpark_actions": [],
            "park_actions": [],
            "candidates": [("42", "execute")],
        }

    monkeypatch.setattr("agent_sessions.driver.router.select", mock_select)
    monkeypatch.setattr("agent_sessions.driver.gh_query.fetch_open_prs", lambda repo: [])
    monkeypatch.setattr("agent_sessions.driver.agent_session_driver.acquire_lock", lambda num, phase, repo: True)
    monkeypatch.setattr("agent_sessions.driver.agent_session_driver.release_lock", lambda repo: None)
    monkeypatch.setattr("agent_sessions.driver.agent_session_driver.increment_attempts", lambda num, repo: None)

    real_sub_run = subprocess.run

    class MockResult:
        stdout = "{}"
        returncode = 0

    def mock_run(cmd, *args, **kwargs):
        # Allow git commands to run real subprocess against dummy_git_repo
        if isinstance(cmd, list) and len(cmd) > 0 and cmd[0] == "git":
            return real_sub_run(cmd, *args, **kwargs)
        if isinstance(cmd, list) and "view" in cmd and "issue" in cmd:
            class IssueView:
                stdout = json.dumps({"comments": []})
                returncode = 0
            return IssueView()
        return MockResult()

    monkeypatch.setattr("subprocess.run", mock_run)

    captured_runner_args = []

    def mock_run_agent(runner_args):
        captured_runner_args.append(runner_args)
        return 0

    monkeypatch.setattr("agent_sessions.driver.agent_runner.run_agent", mock_run_agent)

    argv = [
        "--repo", "owner/repo",
        "--skill-dir", str(tmp_path / "skill"),
        "--allow-nested-skill-dir",
        "--repo-path", str(dummy_git_repo),
        "--state-dir", str(state_dir),
        "--workspaces-dir", str(ws_dir),
        "--issue", "42",
    ]
    (tmp_path / "skill").mkdir(parents=True, exist_ok=True)
    (tmp_path / "skill" / "SKILL.md").write_text("skill", encoding="utf-8")

    ret = agent_session_driver.main(argv)
    assert ret == 0
    assert len(captured_runner_args) == 1

    run_args = captured_runner_args[0]
    assert "--repo-path" in run_args
    repo_idx = run_args.index("--repo-path")
    expected_ws_path = str((ws_dir / "issue-42").resolve())
    assert run_args[repo_idx + 1] == expected_ws_path
    assert (ws_dir / "issue-42").exists()


def test_driver_no_workspace_isolation_flag(dummy_git_repo: Path, tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"

    monkeypatch.setenv("DRIVER_GH_LOGIN", "dummy_bot")
    monkeypatch.setenv("AGENT_GH_READ_TOKEN", "dummy_read_token")
    monkeypatch.setenv("DRIVER_GH_WRITE_TOKEN", "dummy_write_token")

    monkeypatch.setattr("agent_sessions.driver.agent_session_driver.whoami", lambda env: "dummy_bot")

    def mock_select(*args, **kwargs):
        return {
            "messages": [],
            "unpark_actions": [],
            "park_actions": [],
            "candidates": [("42", "execute")],
        }

    monkeypatch.setattr("agent_sessions.driver.router.select", mock_select)
    monkeypatch.setattr("agent_sessions.driver.gh_query.fetch_open_prs", lambda repo: [])
    monkeypatch.setattr("agent_sessions.driver.agent_session_driver.acquire_lock", lambda num, phase, repo: True)
    monkeypatch.setattr("agent_sessions.driver.agent_session_driver.release_lock", lambda repo: None)
    monkeypatch.setattr("agent_sessions.driver.agent_session_driver.increment_attempts", lambda num, repo: None)

    class MockResult:
        stdout = "{}"
        returncode = 0

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: MockResult())

    captured_runner_args = []

    def mock_run_agent(runner_args):
        captured_runner_args.append(runner_args)
        return 0

    monkeypatch.setattr("agent_sessions.driver.agent_runner.run_agent", mock_run_agent)

    argv = [
        "--repo", "owner/repo",
        "--skill-dir", str(tmp_path / "skill"),
        "--allow-nested-skill-dir",
        "--repo-path", str(dummy_git_repo),
        "--state-dir", str(state_dir),
        "--no-workspace-isolation",
        "--issue", "42",
    ]
    (tmp_path / "skill").mkdir(parents=True, exist_ok=True)
    (tmp_path / "skill" / "SKILL.md").write_text("skill", encoding="utf-8")

    ret = agent_session_driver.main(argv)
    assert ret == 0
    assert len(captured_runner_args) == 1

    run_args = captured_runner_args[0]
    repo_idx = run_args.index("--repo-path")
    assert run_args[repo_idx + 1] == str(dummy_git_repo.resolve())


def test_driver_clean_workspaces_flag(dummy_git_repo: Path, tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    ws_dir = tmp_path / "workspaces"

    # Pre-create workspace for issue-999 (stale) and issue-42 (active)
    (ws_dir / "issue-999").mkdir(parents=True, exist_ok=True)
    (ws_dir / "issue-42").mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DRIVER_GH_LOGIN", "dummy_bot")
    monkeypatch.setenv("AGENT_GH_READ_TOKEN", "dummy_read_token")
    monkeypatch.setenv("DRIVER_GH_WRITE_TOKEN", "dummy_write_token")
    monkeypatch.setattr("agent_sessions.driver.agent_session_driver.whoami", lambda env: "dummy_bot")

    def mock_select(*args, **kwargs):
        return {
            "messages": [],
            "unpark_actions": [],
            "park_actions": [],
            "candidates": [("42", "execute")],
        }

    monkeypatch.setattr("agent_sessions.driver.router.select", mock_select)
    monkeypatch.setattr("agent_sessions.driver.gh_query.fetch_open_prs", lambda repo: [])
    monkeypatch.setattr("agent_sessions.driver.agent_session_driver.acquire_lock", lambda num, phase, repo: True)
    monkeypatch.setattr("agent_sessions.driver.agent_session_driver.release_lock", lambda repo: None)
    monkeypatch.setattr("agent_sessions.driver.agent_session_driver.increment_attempts", lambda num, repo: None)

    real_sub_run = subprocess.run

    def mock_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and len(cmd) > 0 and cmd[0] == "git":
            return real_sub_run(cmd, *args, **kwargs)
        class MockResult:
            stdout = "{}"
            returncode = 0
        return MockResult()

    monkeypatch.setattr("subprocess.run", mock_run)
    monkeypatch.setattr("agent_sessions.driver.agent_runner.run_agent", lambda runner_args: 0)

    argv = [
        "--repo", "owner/repo",
        "--skill-dir", str(tmp_path / "skill"),
        "--allow-nested-skill-dir",
        "--repo-path", str(dummy_git_repo),
        "--state-dir", str(state_dir),
        "--workspaces-dir", str(ws_dir),
        "--clean-workspaces",
        "--issue", "42",
    ]
    (tmp_path / "skill").mkdir(parents=True, exist_ok=True)
    (tmp_path / "skill" / "SKILL.md").write_text("skill", encoding="utf-8")

    ret = agent_session_driver.main(argv)
    assert ret == 0
    assert (ws_dir / "issue-42").exists()
    assert not (ws_dir / "issue-999").exists()
