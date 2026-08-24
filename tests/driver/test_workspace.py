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

    assert remove_workspace(dummy_git_repo, ws_path) is True
    assert not ws_path.exists()

    # Re-running remove_workspace when path is gone is a safe no-op. True, not False:
    # an absent workspace was not "kept because dirty".
    assert remove_workspace(dummy_git_repo, ws_path) is True


def test_clean_stale_workspaces(dummy_git_repo: Path, tmp_path: Path):
    state_dir = tmp_path / "state"
    ws_101 = ensure_workspace(dummy_git_repo, get_workspace_path(state_dir, 101), "issue-101", base_ref="main")
    ws_102 = ensure_workspace(dummy_git_repo, get_workspace_path(state_dir, 102), "issue-102", base_ref="main")

    assert ws_101.exists()
    assert ws_102.exists()

    # Active issues is only 101; 102 is stale
    removed, kept_dirty = clean_stale_workspaces(state_dir, dummy_git_repo, active_issue_numbers={"101"})
    assert ws_101.exists()
    assert not ws_102.exists()
    assert removed == [ws_102]
    assert kept_dirty == []


def test_a_dirty_stale_workspace_is_kept_and_reported(dummy_git_repo: Path, tmp_path: Path):
    """#261's decision: the driver's own sweep no longer discards uncommitted work.

    `remove_workspace` ran `git worktree remove --force`, which does not refuse a dirty
    worktree, and then `shutil.rmtree` for anything that survived. `findings.md` records
    a run whose gate block existed only inside such a worktree.

    Both halves are asserted. Keeping the directory is the safety property; returning it
    is what lets the driver say so, and a sweep that silently cleaned nothing would look
    identical to one with nothing to clean.
    """
    state_dir = tmp_path / "state"
    ws_dirty = ensure_workspace(dummy_git_repo, get_workspace_path(state_dir, 201), "issue-201", base_ref="main")
    ws_clean = ensure_workspace(dummy_git_repo, get_workspace_path(state_dir, 202), "issue-202", base_ref="main")
    (ws_dirty / "unsaved.txt").write_text("the only copy of something", encoding="utf-8")

    removed, kept_dirty = clean_stale_workspaces(state_dir, dummy_git_repo, active_issue_numbers=set())

    assert ws_dirty.exists()
    assert (ws_dirty / "unsaved.txt").read_text(encoding="utf-8") == "the only copy of something"
    assert kept_dirty == [ws_dirty]
    assert not ws_clean.exists()
    assert removed == [ws_clean]


def test_a_directory_that_is_not_a_worktree_is_still_removed(dummy_git_repo: Path, tmp_path: Path):
    """The other half of the dirty rule, and the reason it is not `workspace_is_dirty`.

    `git status` fails on a path that is not a repository, and `workspace_is_dirty`
    calls that dirty -- correct for the operator's pruner, where a human reads the list.
    Applied to the driver's sweep it would keep such a directory on every pass forever,
    so the workspaces root could only grow. `holds_uncommitted_work` requires a `.git`
    before it will believe there is anything to lose.
    """
    state_dir = tmp_path / "state"
    debris = state_dir / "workspaces" / "issue-301"
    debris.mkdir(parents=True)
    (debris / "leftover.txt").write_text("not tracked by anything", encoding="utf-8")

    removed, kept_dirty = clean_stale_workspaces(state_dir, dummy_git_repo, active_issue_numbers=set())

    assert not debris.exists()
    assert removed == [debris]
    assert kept_dirty == []


def test_an_unreadable_worktree_is_kept(dummy_git_repo: Path, tmp_path: Path, monkeypatch):
    """A transient `git` failure must not read as a clean tree."""
    state_dir = tmp_path / "state"
    ws = ensure_workspace(dummy_git_repo, get_workspace_path(state_dir, 302), "issue-302", base_ref="main")
    monkeypatch.setattr(
        "agent_sessions.driver.workspace.subprocess.run",
        lambda *a, **k: (_ for _ in ()).throw(OSError("git is not on PATH")),
    )

    removed, kept_dirty = clean_stale_workspaces(state_dir, dummy_git_repo, active_issue_numbers=set())

    assert ws.exists()
    assert kept_dirty == [ws]
    assert removed == []


def test_remove_workspace_refuses_a_dirty_worktree_and_force_overrides(dummy_git_repo: Path, tmp_path: Path):
    """The primitive's contract, and the one caller that legitimately overrides it."""
    ws_path = tmp_path / "workspaces" / "issue-203"
    ensure_workspace(dummy_git_repo, ws_path, "issue-203", base_ref="main")
    (ws_path / "untracked.txt").write_text("x", encoding="utf-8")

    assert remove_workspace(dummy_git_repo, ws_path) is False
    assert ws_path.exists()

    assert remove_workspace(dummy_git_repo, ws_path, force=True) is True
    assert not ws_path.exists()


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
