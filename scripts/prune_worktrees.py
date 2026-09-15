#!/usr/bin/env python3
"""Reclaim development worktrees whose pull request has merged, and keep everything else.

Why this exists
---------------
Development worktrees accumulate because nothing removes them. Measured on `main` at
`1bb3164` on 2026-09-15: 20 linked worktrees holding 1.05 GB, of which 15 were checkouts
of branches whose PR had already merged. This is the second time the pile has been
cleared by hand, which is why the answer is a target rather than another command.

Note what the volume is. Most of a worktree's bytes are its `.venv`, and `make
clean-venvs` reclaims those without removing anything -- so run that first if space is
all you want. This tool is for the *checkouts*, which is a different question: which
lines of work are finished.

The oracle is PR state, not ancestry
------------------------------------
**This repository squash-merges, so `git merge-base --is-ancestor` reports NO for
almost every merged branch.** The merge commit's tree matches, but the branch's commits
are not in `main`'s history -- a squash makes one new commit and discards the lineage.
An earlier by-hand pass using ancestry alone marked 19 fully-merged worktrees as
unmerged, which is the failure that matters here: the tool would look conservative while
being merely wrong, and an operator reading "19 unmerged" learns nothing.

So the question asked of each branch is *"did GitHub merge a PR whose head was you?"*,
answered by `gh pr list --state all`. That is authoritative for squash, rebase and merge
commits alike, because it records the act rather than inferring it from the result.

A checkout is not the work
--------------------------
**`git worktree remove` deletes the checkout, not the branch.** Every commit survives,
reachable from its branch ref, and `git worktree add` re-creates the checkout from it.
That is what makes this chore cheap and reversible, and it is why this tool never
deletes a branch: branch deletion discards commits, so it is a separate decision that
belongs to a human on a different day.

Fail closed, four ways
----------------------
A worktree is removed only when every one of these is true, and each unmet condition is
reported by name rather than folded into a count:

  * `workspace_is_dirty` says clean. Imported from `driver/workspace.py` rather than
    rewritten here -- that module's own docstring anticipates this caller -- because two
    copies of a fail-closed predicate is one copy that can stop failing closed. It reads
    `git status --porcelain`, so untracked files count as dirty and ignored files
    (`.venv`, tool caches) do not.
  * The worktree is on a branch. A detached HEAD has nothing to match against a PR.
  * Some PR with that branch as its head is `MERGED`.
  * No PR with that branch as its head is still `OPEN`.

If the GitHub oracle cannot be reached, nothing is removed and the exit status is
non-zero. An unreachable oracle is not an empty one.

Removal uses plain `git worktree remove`, never `--force`. Verified 2026-09-15: plain
removal succeeds with ignored files present and refuses on modified or untracked content
(`fatal: ... contains modified or untracked files`). So git's own refusal is a second,
independent net behind the dirty check, and passing `--force` would be removing exactly
that net. The driver's `--clean-workspaces` does force, and `findings.md` records an
incident where such a worktree held the only copy of a run's final gate block.

Reporting is the default
------------------------
It prints what it would remove, what it is keeping and why, and removes nothing without
`--confirm`. A deletion tool whose safe mode is the one you have to remember is the
wrong way round; and printing the kept list with reasons means an empty result reads as
empty rather than as success.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from agent_sessions.driver.workspace import workspace_is_dirty


class OracleUnavailable(RuntimeError):
    """GitHub could not be asked which PRs merged. Distinct from 'none merged'."""


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str | None  # None when the checkout is on a detached HEAD


@dataclass(frozen=True)
class Verdict:
    worktree: Worktree
    remove: bool
    reason: str


def _git(cwd: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=60
    )
    if res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout


def main_worktree(repo_root: Path) -> Path:
    """The main checkout, identified rather than assumed to be listed first.

    `git worktree list` does document the main worktree first, but depending on that
    ordering makes the safety of every removal a property of output formatting. The
    common git directory belongs to the main checkout from any worktree, so its parent
    is the answer without reference to position.
    """
    common = _git(repo_root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(common.strip()).resolve().parent


def list_worktrees(repo_root: Path) -> list[Worktree]:
    """Every linked worktree, with the main checkout excluded by identity."""
    main = main_worktree(repo_root)
    out: list[Worktree] = []
    path: Path | None = None
    branch: str | None = None
    for line in _git(repo_root, "worktree", "list", "--porcelain").splitlines() + [""]:
        if line.startswith("worktree "):
            path, branch = Path(line.split(" ", 1)[1]).resolve(), None
        elif line.startswith("branch "):
            branch = line.split(" ", 1)[1].removeprefix("refs/heads/")
        elif line.strip() == "" and path is not None:
            if path != main:
                out.append(Worktree(path, branch))
            path, branch = None, None
    return out


def pr_states(repo_root: Path, limit: int = 1000) -> dict[str, list[tuple[int, str]]]:
    """Branch name -> [(PR number, state)] for every PR the repository has ever had.

    `--state all` is required: the default is open-only, which would report every
    merged branch as having no PR and keep all of them. That failure is safe but
    useless, and it looks identical to a correct empty result.
    """
    try:
        res = subprocess.run(
            [
                "gh", "pr", "list", "--state", "all", "--limit", str(limit),
                "--json", "number,headRefName,state",
            ],
            cwd=repo_root, capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OracleUnavailable(f"could not run gh: {exc}") from exc
    if res.returncode != 0:
        raise OracleUnavailable(f"gh pr list failed: {res.stderr.strip()}")
    try:
        rows = json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        raise OracleUnavailable(f"gh returned unparseable JSON: {exc}") from exc
    states: dict[str, list[tuple[int, str]]] = {}
    for row in rows:
        states.setdefault(row["headRefName"], []).append((row["number"], row["state"]))
    return states


def classify(
    worktrees: list[Worktree],
    prs: dict[str, list[tuple[int, str]]],
    is_dirty: Callable[[Path], bool] = workspace_is_dirty,
) -> list[Verdict]:
    """One verdict per worktree. Dirty is checked first, so it is the reason reported."""
    verdicts: list[Verdict] = []
    for wt in worktrees:
        if is_dirty(wt.path):
            verdicts.append(Verdict(wt, False, "uncommitted or untracked content"))
            continue
        if wt.branch is None:
            verdicts.append(Verdict(wt, False, "detached HEAD -- no branch to match"))
            continue
        states = prs.get(wt.branch, [])
        if not states:
            verdicts.append(Verdict(wt, False, "no pull request -- merge unproven"))
            continue
        if open_prs := [n for n, s in states if s == "OPEN"]:
            verdicts.append(Verdict(wt, False, f"PR #{open_prs[0]} still open"))
            continue
        if merged := [n for n, s in states if s == "MERGED"]:
            verdicts.append(Verdict(wt, True, f"PR #{merged[0]} merged"))
            continue
        closed = [n for n, s in states if s == "CLOSED"]
        verdicts.append(Verdict(wt, False, f"PR #{closed[0]} closed without merging"))
    return verdicts


def tree_size_kb(path: Path) -> int:
    try:
        out = subprocess.run(
            ["du", "-sk", str(path)], capture_output=True, text=True, timeout=120
        )
        return int(out.stdout.split()[0]) if out.returncode == 0 else 0
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return 0


def report_and_remove(
    repo_root: Path, verdicts: list[Verdict], confirm: bool, show_sizes: bool = True
) -> int:
    """Print the two lists, then remove only if asked. Returns a process exit status."""
    keep = [v for v in verdicts if not v.remove]
    drop = [v for v in verdicts if v.remove]

    for v in keep:
        print(f"prune-worktrees: keeping {v.worktree.path} -- {v.reason}")
    if keep:
        print()

    if not drop:
        print(
            f"prune-worktrees: nothing to remove ({len(verdicts)} linked worktree(s), "
            f"{len(keep)} kept)"
        )
        return 0

    total_kb = sum(tree_size_kb(v.worktree.path) for v in drop) if show_sizes else 0
    verb = "removing" if confirm else "would remove"
    size = f", {total_kb / 1e6:.2f} GB" if show_sizes else ""
    print(f"prune-worktrees: {verb} {len(drop)} worktree(s){size}")
    for v in drop:
        print(f"  {v.worktree.path}  ({v.reason})")

    if not confirm:
        print("\nDry run. Re-run with CONFIRM=1 to remove. Branches are never deleted,")
        print("so every commit survives and `git worktree add` re-creates the checkout.")
        return 0

    failed = []
    for v in drop:
        try:
            _git(repo_root, "worktree", "remove", str(v.worktree.path))
            print(f"prune-worktrees: removed {v.worktree.path}")
        except (RuntimeError, subprocess.SubprocessError) as exc:
            failed.append(v.worktree.path)
            print(f"prune-worktrees: REFUSED {v.worktree.path} -- {exc}")
    _git(repo_root, "worktree", "prune")
    print(
        f"prune-worktrees: removed {len(drop) - len(failed)} of {len(drop)} worktree(s)"
        f"{f', {total_kb / 1e6:.2f} GB' if show_sizes else ''}; "
        f"{len(drop) - len(failed)} branch(es) kept, as always"
    )
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repo-root", default=".", help="a checkout of the repository")
    parser.add_argument("--limit", type=int, default=1000, help="PRs to ask GitHub for")
    parser.add_argument("--no-sizes", action="store_true", help="skip the du pass")
    parser.add_argument(
        "--confirm", action="store_true", help="actually remove; otherwise report only"
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    worktrees = list_worktrees(repo_root)
    if not worktrees:
        print(f"prune-worktrees: no linked worktrees under {repo_root}; nothing to do")
        return 0
    try:
        prs = pr_states(repo_root, args.limit)
    except OracleUnavailable as exc:
        print(f"prune-worktrees: {exc}", file=sys.stderr)
        print(
            "prune-worktrees: removing nothing. Merge state is unknown, which is not "
            "the same as unmerged.",
            file=sys.stderr,
        )
        return 2
    verdicts = classify(worktrees, prs)
    return report_and_remove(repo_root, verdicts, args.confirm, not args.no_sizes)


if __name__ == "__main__":
    sys.exit(main())
