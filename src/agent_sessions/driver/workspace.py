import subprocess
from pathlib import Path


def get_workspace_path(
    state_dir: Path,
    issue_number: str | int,
    workspaces_dir: Path | None = None,
) -> Path:
    """Return the absolute path for an issue workspace."""
    base_dir = workspaces_dir if workspaces_dir is not None else state_dir / "workspaces"
    return base_dir / f"issue-{issue_number}"


def ensure_workspace(
    repo_path: Path,
    workspace_path: Path,
    branch_name: str,
    base_ref: str = "origin/main",
    setup_hook: str | None = None,
) -> Path:
    """Ensure git worktree exists at workspace_path, creating it if needed."""
    repo_path = repo_path.resolve()
    workspace_path = workspace_path.resolve()

    if not workspace_path.exists():
        workspace_path.parent.mkdir(parents=True, exist_ok=True)

        # Check if target branch already exists
        check_branch = subprocess.run(
            ["git", "-C", str(repo_path), "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
            capture_output=True,
        )
        if check_branch.returncode == 0:
            cmd = ["git", "-C", str(repo_path), "worktree", "add", str(workspace_path), branch_name]
        else:
            check_ref = subprocess.run(
                ["git", "-C", str(repo_path), "rev-parse", "--verify", "--quiet", base_ref],
                capture_output=True,
            )
            start_ref = base_ref if check_ref.returncode == 0 else "HEAD"
            cmd = ["git", "-C", str(repo_path), "worktree", "add", "-b", branch_name, str(workspace_path), start_ref]

        subprocess.run(cmd, check=True, capture_output=True, text=True)

        if setup_hook:
            subprocess.run(setup_hook, shell=True, cwd=str(workspace_path), check=True)

    return workspace_path


def remove_workspace(repo_path: Path, workspace_path: Path) -> None:
    """Remove git worktree if workspace_path exists."""
    repo_path = repo_path.resolve()
    workspace_path = workspace_path.resolve()

    if workspace_path.exists():
        subprocess.run(
            ["git", "-C", str(repo_path), "worktree", "remove", "--force", str(workspace_path)],
            check=False,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo_path), "worktree", "prune"],
            check=False,
            capture_output=True,
        )
        if workspace_path.exists():
            import shutil
            shutil.rmtree(workspace_path, ignore_errors=True)


def clean_stale_workspaces(
    state_dir: Path,
    repo_path: Path,
    active_issue_numbers: set[str] | set[int] | set[str | int],
    workspaces_dir: Path | None = None,
) -> list[Path]:
    """Remove workspaces for issues not in active_issue_numbers."""
    base_dir = (workspaces_dir if workspaces_dir is not None else state_dir / "workspaces").resolve()
    removed: list[Path] = []
    if not base_dir.exists():
        return removed

    active_strs = {str(n) for n in active_issue_numbers}
    for child in base_dir.iterdir():
        if child.is_dir() and child.name.startswith("issue-"):
            issue_num = child.name.removeprefix("issue-")
            if issue_num not in active_strs:
                remove_workspace(repo_path, child)
                removed.append(child)

    return removed
