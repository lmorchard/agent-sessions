import subprocess
from pathlib import Path

import pytest

from agent_sessions.driver.workspace import (
    clean_stale_workspaces,
    ensure_workspace,
    get_workspace_path,
    remove_workspace,
)


def test_get_workspace_path_default(tmp_path: Path):
    state_dir = tmp_path / "state"
    ws_path = get_workspace_path(state_dir, 150)
    assert ws_path == state_dir / "workspaces" / "issue-150"


def test_get_workspace_path_custom(tmp_path: Path):
    state_dir = tmp_path / "state"
    custom_dir = tmp_path / "custom_workspaces"
    ws_path = get_workspace_path(state_dir, 150, workspaces_dir=custom_dir)
    assert ws_path == custom_dir / "issue-150"


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


def test_ensure_workspace_creates_worktree_and_runs_hook(dummy_git_repo: Path, tmp_path: Path):
    ws_path = tmp_path / "workspaces" / "issue-150"
    setup_marker = ws_path / "setup_done.txt"

    created_path = ensure_workspace(
        repo_path=dummy_git_repo,
        workspace_path=ws_path,
        branch_name="issue-150",
        base_ref="main",
        setup_hook=f"echo 'ready' > '{setup_marker}'",
    )

    assert created_path == ws_path
    assert ws_path.exists()
    assert (ws_path / "README.md").read_text(encoding="utf-8") == "hello"
    assert setup_marker.read_text(encoding="utf-8").strip() == "ready"

    # Re-running ensure_workspace on existing workspace is idempotent
    recreated_path = ensure_workspace(
        repo_path=dummy_git_repo,
        workspace_path=ws_path,
        branch_name="issue-150",
        base_ref="main",
    )
    assert recreated_path == ws_path


def test_remove_workspace(dummy_git_repo: Path, tmp_path: Path):
    ws_path = tmp_path / "workspaces" / "issue-150"
    ensure_workspace(
        repo_path=dummy_git_repo,
        workspace_path=ws_path,
        branch_name="issue-150",
        base_ref="main",
    )
    assert ws_path.exists()

    remove_workspace(dummy_git_repo, ws_path)
    assert not ws_path.exists()

    # Re-running remove_workspace when path is gone is a safe no-op
    remove_workspace(dummy_git_repo, ws_path)


def test_clean_stale_workspaces(dummy_git_repo: Path, tmp_path: Path):
    state_dir = tmp_path / "state"
    ws_101 = ensure_workspace(dummy_git_repo, get_workspace_path(state_dir, 101), "issue-101", base_ref="main")
    ws_102 = ensure_workspace(dummy_git_repo, get_workspace_path(state_dir, 102), "issue-102", base_ref="main")

    assert ws_101.exists()
    assert ws_102.exists()

    # Active issues is only 101; 102 is stale
    removed = clean_stale_workspaces(state_dir, dummy_git_repo, active_issue_numbers={"101"})
    assert ws_101.exists()
    assert not ws_102.exists()
    assert ws_102 in removed


def test_ensure_workspace_recreates_corrupted_directory(dummy_git_repo: Path, tmp_path: Path):
    ws_path = tmp_path / "workspaces" / "issue-150"
    ws_path.mkdir(parents=True, exist_ok=True)
    (ws_path / "stale_file.txt").write_text("corrupted", encoding="utf-8")

    # Directory exists without .git file; ensure_workspace must recover and create valid worktree
    created_path = ensure_workspace(
        repo_path=dummy_git_repo,
        workspace_path=ws_path,
        branch_name="issue-150",
        base_ref="main",
    )

    assert created_path == ws_path
    assert (ws_path / ".git").exists()
    assert (ws_path / "README.md").read_text(encoding="utf-8") == "hello"


def test_remove_workspace_symlink(dummy_git_repo: Path, tmp_path: Path):
    ws_path = tmp_path / "workspaces" / "issue-symlink"
    target_dir = tmp_path / "target_dir"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "keep_me.txt").write_text("don't delete", encoding="utf-8")

    ws_path.parent.mkdir(parents=True, exist_ok=True)
    ws_path.symlink_to(target_dir)

    remove_workspace(dummy_git_repo, ws_path)

    # Symlink is removed, but symlink target directory remains intact
    assert not ws_path.is_symlink()
    assert target_dir.exists()
    assert (target_dir / "keep_me.txt").read_text(encoding="utf-8") == "don't delete"
