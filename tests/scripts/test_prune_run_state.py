"""Frozen acceptance checks for #261 H5 — pruning never reaches the provenance ledger.

`runs.jsonl` is this project's per-run provenance. `CLAUDE.md` instructs readers twice to
cite `make evidence` instead of writing a number down, and `make evidence` reads these
ledgers. A prune tool that could remove one would quietly delete the answer to every
world-state question the docs are forbidden from answering themselves.

So the protection is asserted here rather than left to the implementation's intent, and
asserted the strong way: the checks build a state root containing every protected file
*and* a stale run directory, run the tool for real with `--confirm`, and require the
protected files to survive byte for byte.

The second subject is workspaces, and their rule is different. A workspace is a git
worktree of the target repo, so age says nothing about whether it holds work — dirtiness
does. The driver's own `--clean-workspaces` removes with `git worktree remove --force`,
which does not refuse a dirty worktree; `findings.md` records an incident where exactly
such a worktree held the only copy of a run's final gate block. Measured on the live state
root: 5 of 21 workspaces are dirty, so that is not a hypothetical.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import prune_run_state  # noqa: E402

OLD = time.time() - 400 * 86400


def state_root(tmp_path: Path) -> Path:
    """A state root shaped like a real one: ledger, park log, inbox, marker, runs."""
    root = tmp_path / "agent-session"
    repo = root / "owner-repo"
    (repo / "runs").mkdir(parents=True)
    (repo / "runs.jsonl").write_text('{"issue": 1, "outcome": "gate-eligible"}\n', encoding="utf-8")
    (repo / "parked.jsonl").write_text('{"issue": 2}\n', encoding="utf-8")
    (repo / "inbox.md").write_text("# work queue\n", encoding="utf-8")
    (repo / "inflight.json").write_text('{"issue": 3}\n', encoding="utf-8")

    stale = repo / "runs" / "1-20250101T000000Z"
    stale.mkdir()
    (stale / "stream.jsonl").write_text("x" * 100, encoding="utf-8")
    import os
    os.utime(stale, (OLD, OLD))

    fresh = repo / "runs" / "2-20260819T000000Z"
    fresh.mkdir()
    (fresh / "stream.jsonl").write_text("y" * 100, encoding="utf-8")
    return root


def test_confirmed_prune_removes_the_stale_run_and_keeps_every_protected_file(tmp_path):
    """C1. The load-bearing one: a real removal, and the ledger survives it."""
    root = state_root(tmp_path)
    repo = root / "owner-repo"
    before = {name: (repo / name).read_bytes() for name in prune_run_state.PROTECTED}

    rc = prune_run_state.main(["--state-root", str(root), "--keep-days", "30", "--confirm"])

    assert rc == 0
    assert not (repo / "runs" / "1-20250101T000000Z").exists(), "the stale run was not removed"
    assert (repo / "runs" / "2-20260819T000000Z").exists(), "a fresh run was removed"
    for name, content in before.items():
        assert (repo / name).read_bytes() == content, f"{name} was modified or removed"


def test_dry_run_is_the_default_and_removes_nothing(tmp_path):
    """C2. The safe mode must be the one you get without remembering anything."""
    root = state_root(tmp_path)
    stale = root / "owner-repo" / "runs" / "1-20250101T000000Z"

    rc = prune_run_state.main(["--state-root", str(root), "--keep-days", "30"])

    assert rc == 0
    assert stale.exists(), "a run directory was removed without --confirm"


def test_an_empty_result_says_so(tmp_path, capsys):
    """C3. Nothing to prune must read as nothing, not as success."""
    root = state_root(tmp_path)

    prune_run_state.main(["--state-root", str(root), "--keep-days", "3650"])

    out = capsys.readouterr().out
    assert "nothing to prune" in out


def test_no_protected_filename_is_ever_a_removal_candidate(tmp_path):
    """C4. The rule stated as a property, independent of what the fixture happens to hold.

    `stale_run_dirs` only ever descends into `<repo>/runs/`, so the ledger is out of its
    reach by construction rather than by an exclusion list someone can edit past. This
    asserts the construction.
    """
    root = state_root(tmp_path)
    candidates = prune_run_state.stale_run_dirs(root, keep_days=0, now=time.time())

    assert candidates, "the fixture produced no candidates, so this check proves nothing"
    for c in candidates:
        assert c.parent.name == "runs", f"{c} is not under a runs/ directory"
        assert c.name not in prune_run_state.PROTECTED


# --- workspaces: pruned by dirtiness, never by age ---------------------------


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def workspace(root: Path, name: str, *, dirty: bool) -> Path:
    ws = root / "owner-repo" / "workspaces" / name
    ws.mkdir(parents=True)
    git("init", "-b", "main", cwd=ws)
    (ws / "f.txt").write_text("committed\n", encoding="utf-8")
    git("add", "f.txt", cwd=ws)
    git("commit", "-m", "initial", cwd=ws)
    if dirty:
        (ws / "uncommitted.txt").write_text("the only copy of something\n", encoding="utf-8")
    return ws


def test_a_dirty_workspace_is_kept_and_a_clean_one_is_pruned(tmp_path):
    """C5. The whole reason this tool exists rather than calling --clean-workspaces."""
    root = state_root(tmp_path)
    dirty = workspace(root, "issue-11", dirty=True)
    clean = workspace(root, "issue-12", dirty=False)

    rc = prune_run_state.main(
        ["--state-root", str(root), "--keep-days", "30", "--workspaces", "--confirm"]
    )

    assert rc == 0
    assert dirty.exists(), "a workspace with uncommitted content was removed"
    assert (dirty / "uncommitted.txt").read_text() == "the only copy of something\n"
    assert not clean.exists(), "a clean workspace was not pruned"


def test_workspaces_are_untouched_unless_asked_for(tmp_path):
    """C6. Control. `prune-state` on its own is about run directories."""
    root = state_root(tmp_path)
    clean = workspace(root, "issue-12", dirty=False)

    prune_run_state.main(["--state-root", str(root), "--keep-days", "30", "--confirm"])

    assert clean.exists(), "a workspace was removed without --workspaces"


def test_an_unreadable_workspace_counts_as_dirty(tmp_path):
    """C7. A worktree whose state cannot be determined is the one not to force-remove.

    Defaulting the other way would make an error look like a clean tree, which is the
    null-as-positive shape -- here with data loss as the consequence.
    """
    not_a_repo = tmp_path / "owner-repo" / "workspaces" / "issue-99"
    not_a_repo.mkdir(parents=True)

    assert prune_run_state.workspace_is_dirty(not_a_repo) is True
