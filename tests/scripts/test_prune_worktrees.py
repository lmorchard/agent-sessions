"""Frozen acceptance checks for #272 -- reclaiming merged worktrees without losing work.

Three facts make the naive version of this chore wrong, and each one is asserted here
rather than left to the implementation's intent.

**This repository squash-merges.** `git merge-base --is-ancestor` therefore answers NO
for a branch that GitHub has already merged, and a by-hand pass using ancestry alone
marked 19 fully-merged worktrees as unmerged. `test_ancestry_disagrees_with_the_pr_oracle`
builds a real squash merge and pins both answers, so the reason the oracle is PR state
survives as a check rather than as a paragraph.

**A checkout is not the work.** `git worktree remove` discards the checkout and leaves
every commit reachable from its branch, which is what makes the chore reversible. The
branch-survival assertion rides along with the removal test for that reason.

**Clean is decided by the shared predicate, and git refuses as well.** The tool imports
`workspace_is_dirty` instead of re-deriving it, and removes with plain `git worktree
remove` -- so a tree that goes dirty after classification is still refused.
`test_removal_refuses_a_tree_that_went_dirty_after_classification` lies to the classifier
on purpose to exercise that second net, which is the net `--force` would have removed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import prune_worktrees  # noqa: E402

MERGED = {"feat": [(7, "MERGED")]}


def git(cwd: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return res.stdout


def make_repo(tmp_path: Path) -> Path:
    """A repository that ignores `.venv`, as every worktree here does."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    (root / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    (root / "file.txt").write_text("one\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init")
    return root


def add_worktree(root: Path, name: str, branch: str = "feat") -> Path:
    path = root.parent / name
    git(root, "worktree", "add", "-q", str(path), "-b", branch)
    return path


def test_merged_and_clean_worktree_is_removed_and_its_branch_survives(tmp_path):
    root = make_repo(tmp_path)
    wt = add_worktree(root, "wt")

    verdicts = prune_worktrees.classify(prune_worktrees.list_worktrees(root), MERGED)
    assert prune_worktrees.report_and_remove(root, verdicts, confirm=True) == 0

    assert not wt.exists()
    assert "feat" in git(root, "branch", "--list", "feat")
    assert git(root, "rev-parse", "--verify", "-q", "refs/heads/feat").strip()


def test_default_is_report_only(tmp_path):
    root = make_repo(tmp_path)
    wt = add_worktree(root, "wt")

    verdicts = prune_worktrees.classify(prune_worktrees.list_worktrees(root), MERGED)
    assert prune_worktrees.report_and_remove(root, verdicts, confirm=False) == 0

    assert wt.is_dir()
    assert (wt / "file.txt").is_file()


def test_dirty_worktree_is_kept_by_the_shared_predicate(tmp_path, capsys):
    """No injected predicate: the imported `workspace_is_dirty` must see the dirt."""
    root = make_repo(tmp_path)
    wt = add_worktree(root, "wt")
    (wt / "scratch.py").write_text("x = 1\n", encoding="utf-8")

    verdicts = prune_worktrees.classify(prune_worktrees.list_worktrees(root), MERGED)
    assert prune_worktrees.report_and_remove(root, verdicts, confirm=True) == 0

    assert (wt / "scratch.py").read_text(encoding="utf-8") == "x = 1\n"
    assert "uncommitted or untracked" in capsys.readouterr().out


def test_modified_tracked_file_is_also_dirty(tmp_path):
    root = make_repo(tmp_path)
    wt = add_worktree(root, "wt")
    (wt / "file.txt").write_text("edited\n", encoding="utf-8")

    verdicts = prune_worktrees.classify(prune_worktrees.list_worktrees(root), MERGED)
    prune_worktrees.report_and_remove(root, verdicts, confirm=True)

    assert (wt / "file.txt").read_text(encoding="utf-8") == "edited\n"


def test_ignored_venv_does_not_count_as_dirty(tmp_path):
    """Most of a worktree's bytes are its ignored `.venv`; it must not block removal."""
    root = make_repo(tmp_path)
    wt = add_worktree(root, "wt")
    (wt / ".venv" / "lib").mkdir(parents=True)
    (wt / ".venv" / "lib" / "big.txt").write_text("junk\n", encoding="utf-8")

    verdicts = prune_worktrees.classify(prune_worktrees.list_worktrees(root), MERGED)
    prune_worktrees.report_and_remove(root, verdicts, confirm=True)

    assert not wt.exists()


def test_open_pr_keeps_the_worktree(tmp_path):
    root = make_repo(tmp_path)
    wt = add_worktree(root, "wt")
    prs = {"feat": [(7, "MERGED"), (9, "OPEN")]}

    verdicts = prune_worktrees.classify(prune_worktrees.list_worktrees(root), prs)
    prune_worktrees.report_and_remove(root, verdicts, confirm=True)

    assert wt.is_dir()
    assert [v.reason for v in verdicts] == ["PR #9 still open"]


def test_no_pr_keeps_the_worktree(tmp_path):
    root = make_repo(tmp_path)
    wt = add_worktree(root, "wt")

    verdicts = prune_worktrees.classify(prune_worktrees.list_worktrees(root), {})
    prune_worktrees.report_and_remove(root, verdicts, confirm=True)

    assert wt.is_dir()
    assert not verdicts[0].remove


def test_closed_unmerged_pr_keeps_the_worktree(tmp_path):
    root = make_repo(tmp_path)
    wt = add_worktree(root, "wt")

    verdicts = prune_worktrees.classify(
        prune_worktrees.list_worktrees(root), {"feat": [(7, "CLOSED")]}
    )
    prune_worktrees.report_and_remove(root, verdicts, confirm=True)

    assert wt.is_dir()
    assert verdicts[0].reason == "PR #7 closed without merging"


def test_detached_head_is_kept(tmp_path):
    root = make_repo(tmp_path)
    wt = add_worktree(root, "wt")
    git(wt, "checkout", "-q", "--detach")

    listed = prune_worktrees.list_worktrees(root)
    assert [w.branch for w in listed] == [None]

    verdicts = prune_worktrees.classify(listed, MERGED)
    prune_worktrees.report_and_remove(root, verdicts, confirm=True)
    assert wt.is_dir()


def test_main_worktree_is_never_a_candidate(tmp_path):
    root = make_repo(tmp_path)
    add_worktree(root, "wt")

    paths = [w.path for w in prune_worktrees.list_worktrees(root)]
    assert root.resolve() not in paths
    assert len(paths) == 1


def test_main_worktree_is_excluded_when_listed_from_a_linked_worktree(tmp_path):
    """The exclusion is by identity, so it cannot depend on git's output ordering."""
    root = make_repo(tmp_path)
    wt = add_worktree(root, "wt")

    assert prune_worktrees.main_worktree(wt) == root.resolve()
    assert root.resolve() not in [w.path for w in prune_worktrees.list_worktrees(wt)]


def test_removal_refuses_a_tree_that_went_dirty_after_classification(tmp_path):
    """Plain `git worktree remove` is the second net. `--force` would delete it."""
    root = make_repo(tmp_path)
    wt = add_worktree(root, "wt")

    verdicts = prune_worktrees.classify(
        prune_worktrees.list_worktrees(root), MERGED, is_dirty=lambda _p: False
    )
    assert verdicts[0].remove
    (wt / "late.txt").write_text("appeared after classification\n", encoding="utf-8")

    assert prune_worktrees.report_and_remove(root, verdicts, confirm=True) == 1
    assert (wt / "late.txt").is_file()


def test_ancestry_disagrees_with_the_pr_oracle(tmp_path):
    """A real squash merge: ancestry says unmerged, the PR oracle says merged."""
    root = make_repo(tmp_path)
    wt = add_worktree(root, "wt")
    (wt / "feature.txt").write_text("work\n", encoding="utf-8")
    git(wt, "add", "-A")
    git(wt, "commit", "-qm", "the feature")
    git(root, "merge", "-q", "--squash", "feat")
    git(root, "commit", "-qm", "the feature (#7)")

    ancestry = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", "feat", "main"],
        capture_output=True,
    )
    assert ancestry.returncode != 0, "squash merge should defeat ancestry"
    assert (root / "feature.txt").read_text(encoding="utf-8") == "work\n"

    verdicts = prune_worktrees.classify(prune_worktrees.list_worktrees(root), MERGED)
    assert verdicts[0].remove
    assert prune_worktrees.report_and_remove(root, verdicts, confirm=True) == 0
    assert not wt.exists()


def test_unreachable_oracle_removes_nothing(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    wt = add_worktree(root, "wt")

    def unavailable(*_a, **_k):
        raise prune_worktrees.OracleUnavailable("gh exploded")

    monkeypatch.setattr(prune_worktrees, "pr_states", unavailable)
    status = prune_worktrees.main(["--repo-root", str(root), "--confirm"])

    assert status == 2
    assert wt.is_dir()


def test_no_linked_worktrees_is_reported_not_silent(tmp_path, capsys):
    root = make_repo(tmp_path)
    assert prune_worktrees.main(["--repo-root", str(root)]) == 0
    assert "no linked worktrees" in capsys.readouterr().out
