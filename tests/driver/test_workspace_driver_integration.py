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


@pytest.fixture(autouse=True)
def no_repo_env(tmp_path: Path, monkeypatch):
    """Run from a directory with no `.env`, so this repo's own settings cannot leak in.

    `load_env_file(".env")` reads the **current directory**. These tests never left the
    repository root, so on a machine with a real `.env` the driver picked up its `BOARD`
    and issued `gh project item-list 6 --owner lmorchard` — a query against a live board,
    from a unit test.

    It passed anyway until now, because the fake these tests used answered every
    unmodelled call with success. Replacing that fake made the leak visible on the first
    run in a checkout that has a `.env`, and invisible in one that does not.

    `test_full_loop.py`'s harness has done this since it was written, with the same
    reason in a comment. This suite never did.
    """
    monkeypatch.chdir(tmp_path)


def model_github(gh):
    """Model the GitHub reads a driver pass makes, and nothing else.

    Everything unmatched lands in `gh.unhandled` and fails the test on teardown. That is
    the whole point of the change: these three tests used to answer every unmodelled call
    with `stdout="{}"`, `returncode=0`, so they would have passed if the driver started
    issuing an entirely different set of commands.
    """
    # Modelled call by call, on purpose. A `gh.on(a[:1] == ["gh"], "{}")` line would be
    # the same catch-all in a new coat -- I wrote one, and a mutation test proved it: a
    # freshly-added `gh api rate_limit` sailed straight through it. The point of the
    # change is that a call the driver did not previously make has to be noticed.
    gh.on(lambda a: a[:1] == ["gh"] and "issue" in a and "view" in a,
          json.dumps({"comments": []}))
    gh.on(lambda a: a[:3] == ["gh", "api", "user"], "dummy_bot\n")
    gh.on(lambda a: a[:3] == ["gh", "api", "rate_limit"],
          json.dumps({"resources": {"core": {"remaining": 5000, "limit": 5000}},
                      "rate": {"remaining": 5000, "limit": 5000}}))
    gh.on(lambda a: a[:3] == ["gh", "api", "graphql"],
          json.dumps({"data": {"repository": {"pullRequests": {"nodes": []}}}}))
    gh.on(lambda a: a[:2] == ["gh", "issue"] and "list" in a, "[]")
    gh.on(lambda a: a[:2] == ["gh", "discussion"] and "list" in a, "[]")
    gh.on(lambda a: a[:2] == ["gh", "discussion"] and "create" in a,
          "https://github.com/owner/repo/discussions/1\n")
    gh.on(lambda a: a[:2] == ["gh", "discussion"] and "comment" in a, "commented")

    # The driver shells out to `label_manager.py` to park and unpark. The old catch-all
    # answered these with success too, so all three tests were exercising a park none of
    # them asserted on. Recorded here so a test can, and so an unexpected label operation
    # is visible rather than free.
    gh.label_ops = []
    gh.on(
        lambda a: any(str(tok).endswith("label_manager.py") for tok in a),
        lambda argv: (gh.label_ops.append(argv[argv.index("--repo") + 2:]) or ""),
    )
    return gh


def test_driver_workspace_isolation_enabled(dummy_git_repo: Path, tmp_path: Path, monkeypatch, recording_gh):
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

    model_github(recording_gh)

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

    # Surfaced by the strict fake: the pass parks #42, and nothing asserted it before,
    # because the catch-all answered the `label_manager` invocation with success.
    assert recording_gh.label_ops == [["park", "--issue", "42"]], recording_gh.label_ops

def test_driver_no_workspace_isolation_flag(dummy_git_repo: Path, tmp_path: Path, monkeypatch, recording_gh):
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


    model_github(recording_gh)

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


def test_driver_clean_workspaces_flag(dummy_git_repo: Path, tmp_path: Path, monkeypatch, recording_gh):
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

    model_github(recording_gh)
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
