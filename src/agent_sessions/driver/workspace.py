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

    if workspace_path.is_symlink():
        workspace_path.unlink()

    # Check if workspace exists and is a valid git worktree
    is_valid_worktree = workspace_path.exists() and (workspace_path / ".git").exists()
    if workspace_path.exists() and not is_valid_worktree:
        # Force: the path is occupied by something that is not a worktree, so the
        # dirty check has nothing to read and must not veto clearing the obstruction.
        remove_workspace(repo_path, workspace_path, force=True)

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


def workspace_is_dirty(path: Path) -> bool:
    """True if the worktree holds uncommitted or untracked content, or cannot be read.

    Unreadable counts as dirty. A worktree whose state we cannot determine is exactly
    the one not to force-remove, and defaulting the other way would make an error look
    like a clean tree.

    Lives here rather than in `scripts/prune_run_state.py`, where it was written: both
    the driver's own sweep and the operator's pruner need the same answer, and two
    copies of a fail-closed predicate is one copy that can stop failing closed.
    """
    try:
        res = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    if res.returncode != 0:
        return True
    return bool(res.stdout.strip())


def holds_uncommitted_work(path: Path) -> bool:
    """Dirty *and* actually a worktree — the narrower question the driver's sweep asks.

    `workspace_is_dirty` answers True for a path git cannot read at all, which is the
    right default for the operator's pruner: a human reads that list and decides. The
    driver decides alone and forever, so the same answer there means a directory that is
    not a worktree is kept on every pass, for good, and the workspaces root only grows.

    `.git` is the discriminator, and deliberately the same one `ensure_workspace` uses to
    call a path an obstruction rather than a workspace. So:

    - a worktree git reports as dirty -- keep, that is the decision;
    - a worktree git cannot read -- keep, because a transient `git` failure must not read
      as a clean tree;
    - a path with no `.git` -- remove, because nothing there is recoverable through git
      and no later pass will find it any more readable.
    """
    if not (path / ".git").exists():
        return False
    return workspace_is_dirty(path)


def remove_workspace(repo_path: Path, workspace_path: Path, *, force: bool = False) -> bool:
    """Remove the worktree at `workspace_path`. False if it was kept because it is dirty.

    `force` skips the dirty check. It exists for one caller: `ensure_workspace` clearing
    a path that is occupied but is *not* a worktree, where `workspace_is_dirty` has
    nothing to read and would answer True for an obstruction that must go.

    Removal used to be unconditional -- `git worktree remove --force`, which does not
    refuse a dirty worktree, and then `shutil.rmtree` for whatever survived. `findings.md`
    records a run whose gate block existed only inside such a worktree.
    """
    repo_path = repo_path.resolve()

    if workspace_path.is_symlink():
        workspace_path.unlink()
        return True

    if not force and workspace_path.exists() and holds_uncommitted_work(workspace_path):
        return False

    if workspace_path.exists():
        resolved_ws = workspace_path.resolve()
        subprocess.run(
            ["git", "-C", str(repo_path), "worktree", "remove", "--force", str(resolved_ws)],
            check=False,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo_path), "worktree", "prune"],
            check=False,
            capture_output=True,
        )
        if resolved_ws.exists():
            import shutil
            shutil.rmtree(resolved_ws, ignore_errors=True)
    return True


def clean_stale_workspaces(
    state_dir: Path,
    repo_path: Path,
    active_issue_numbers: set[str] | set[int] | set[str | int],
    workspaces_dir: Path | None = None,
) -> tuple[list[Path], list[Path]]:
    """(removed, kept-because-dirty) for workspaces of issues not in active_issue_numbers.

    Both halves are returned, so the caller can report what it declined to do. A count
    of what was cleaned, with nothing said about what was skipped, is the shape this
    project treats as a null rendering as a positive.
    """
    base_dir = (workspaces_dir if workspaces_dir is not None else state_dir / "workspaces").resolve()
    removed: list[Path] = []
    kept_dirty: list[Path] = []
    if not base_dir.exists():
        return removed, kept_dirty

    active_strs = {str(n) for n in active_issue_numbers}
    for child in sorted(base_dir.iterdir()):
        if child.is_dir() and child.name.startswith("issue-"):
            issue_num = child.name.removeprefix("issue-")
            if issue_num not in active_strs:
                if remove_workspace(repo_path, child):
                    removed.append(child)
                else:
                    kept_dirty.append(child)

    return removed, kept_dirty
