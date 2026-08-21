#!/usr/bin/env python3
"""Drop old per-run directories from the driver's state root, and never the ledger.

Why this exists
---------------
Nothing pruned run state and there was no `make clean` of any kind. Measured
2026-08-19 under `~/.local/state/agent-session/lmorchard-decafclaw/`:

    workspaces/   3.1 GB   21 git worktrees of the target repo
    runs/          79 MB   287 per-run directories
    runs.jsonl    204 KB   the ledger

So the volume is **workspaces**, not run streams -- worth stating, because the finding
this came from attributed 3.2 GB to "287 run directories with no retention", and acting
on that would have reclaimed 79 MB and left the actual 3.1 GB in place. Both are pruned
here, by different rules, because they are different things.

The split that makes run pruning safe is lopsided. Per-run streams -- `stream.jsonl`,
`stderr.txt`, `prompt.txt` -- are diagnostic and stop being interesting once a run is
understood. The *evidence* is `runs.jsonl`, one line per run, 221 KB across both
repositories. The durable record is a fraction of a percent of the volume.

**`runs.jsonl` is never a candidate here, and that is asserted rather than intended**
(`tests/scripts/test_prune_run_state.py`). Same for `parked.jsonl`, `inbox.md` and
`inflight.json`: the first two are human work queues, and the third is what
`--classify-only` recovers a dead run from. Only whole directories under `runs/` are
ever removed.

Workspaces are pruned by dirtiness, not by age
---------------------------------------------
A workspace is a git worktree of the *target* repo. The driver already has a mechanism
for these -- `--clean-workspaces`, which nobody passes, which is why 21 accumulated --
but it removes with `git worktree remove --force`, and **force does not refuse a dirty
worktree**. `findings.md` records an incident where exactly such a worktree held the
only copy of a run's final gate block and its governance note.

So this tool never touches a workspace with uncommitted or untracked content. It reports
those and leaves them, which is the opposite default from the driver's own path and
deliberately so: the driver is cleaning up after a run it just supervised, and an
operator running a prune is not.

Dry run is the default
----------------------
It prints what it would remove and how much that is, and removes nothing without
`--confirm`. Two reasons. A deletion tool whose safe mode is the one you have to
remember is the wrong way round; and printing the count means an empty result reads as
empty rather than as success, which is this project's most-repeated lesson.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

#: Never removed, whatever their age. The ledger first, because it is the point.
PROTECTED = ("runs.jsonl", "parked.jsonl", "inbox.md", "inflight.json")


def default_state_root() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "agent-session"


def dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def stale_run_dirs(state_root: Path, keep_days: int, now: float) -> list[Path]:
    """Run directories older than the window, across every per-repo state directory.

    Only `<repo>/runs/<child>` is ever considered. Anything else under the state root --
    the ledger, the park log, the inbox, the inflight marker, the workspaces tree -- is
    outside this function's reach by construction rather than by exclusion, which is the
    difference between a rule and a filter someone can edit past.
    """
    cutoff = now - keep_days * 86400
    stale = []
    for repo_dir in sorted(p for p in state_root.iterdir() if p.is_dir()):
        runs = repo_dir / "runs"
        if not runs.is_dir():
            continue
        for run in sorted(p for p in runs.iterdir() if p.is_dir()):
            if run.stat().st_mtime < cutoff:
                stale.append(run)
    return stale


def workspace_is_dirty(path: Path) -> bool:
    """True if the worktree holds uncommitted or untracked content, or cannot be read.

    Unreadable counts as dirty. A worktree whose state we cannot determine is exactly
    the one not to force-remove, and defaulting the other way would make an error look
    like a clean tree.
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


def stale_workspaces(state_root: Path) -> tuple[list[Path], list[Path]]:
    """(prunable, kept-because-dirty) workspace directories across every repo state dir."""
    prunable: list[Path] = []
    dirty: list[Path] = []
    for repo_dir in sorted(p for p in state_root.iterdir() if p.is_dir()):
        base = repo_dir / "workspaces"
        if not base.is_dir():
            continue
        for ws in sorted(p for p in base.iterdir() if p.is_dir()):
            (dirty if workspace_is_dirty(ws) else prunable).append(ws)
    return prunable, dirty


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--state-root", default=None, help="defaults to the driver's own")
    parser.add_argument("--keep-days", type=int, default=30)
    parser.add_argument("--confirm", action="store_true", help="actually remove; otherwise dry run")
    parser.add_argument(
        "--workspaces",
        action="store_true",
        help="also prune per-issue git worktrees, skipping any with uncommitted content",
    )
    args = parser.parse_args(argv)

    root = Path(args.state_root) if args.state_root else default_state_root()
    if not root.is_dir():
        print(f"prune-state: no state root at {root}; nothing to do")
        return 0

    stale = stale_run_dirs(root, args.keep_days, time.time())

    dirty: list[Path] = []
    if args.workspaces:
        prunable_ws, dirty = stale_workspaces(root)
        stale += prunable_ws
        for ws in dirty:
            print(f"prune-state: keeping {ws} -- it has uncommitted or untracked content")

    if not stale:
        print(
            f"prune-state: nothing to prune under {root} "
            f"(run directories older than {args.keep_days} days"
            f"{', prunable workspaces' if args.workspaces else ''})"
        )
        return 0

    total = sum(dir_size(d) for d in stale)
    verb = "removing" if args.confirm else "would remove"
    print(f"prune-state: {verb} {len(stale)} run director(ies), {total / 1e9:.2f} GB, under {root}")
    for d in stale:
        print(f"  {d}")

    if not args.confirm:
        print("\nDry run. Re-run with CONFIRM=1 to remove. The ledgers are never touched:")
        for name in PROTECTED:
            print(f"  kept: {name}")
        return 0

    for d in stale:
        shutil.rmtree(d)
    print(f"prune-state: removed {len(stale)} run director(ies), {total / 1e9:.2f} GB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
