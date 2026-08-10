#!/usr/bin/env python3
"""Detect documentation rot mechanically, rather than asking people to be careful.

Why this exists
---------------
Every documentation defect this project has hit was one of two things:

  1. a fact **derivable from a live source** that had since changed -- "21 fixture
     tests" (was 61), "seven PRs, six merged" (was eight and all merged),
     "~1,880 lines of markdown", "two grep assertions" (were eight), a
     "49-assertion fixture suite" that sat stale in CLAUDE.md;
  2. prose **duplicating a live source** -- design.md's roadmap restating the
     board, prose above a table restating the table's own conclusions.

Nothing that rotted was a judgment or a rule. `findings.md`'s rules are as true as
the day they were written; its *counts* drifted. So the rule is: **a document
should not state a fact a command can print.**

A CLAUDE.md line saying that would be an exhortation, and this project is 3 for 3
on added rules measuring away (see docs/findings.md defect class 4). Mechanical
detectors have worked every time. So this is a detector.

It checks three things, each motivated by a defect actually found:

  * every relative markdown link resolves  -- caught real breakage twice while
    relocating docs into archive/, in both cases invisible to reading;
  * no orphaned table rows            -- a prose block split a table in
    findings.md, leaving two rows to render headerless;
  * claimed assertion counts match reality -- the "49-assertion" class.

Stdlib only, and it **reports a skipped check as skipped, never as a pass** --
this project's most-repeated lesson is that a null must not render as a positive,
and a checker that quietly skips is the same defect one level up.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SKIP_DIRS = {".git", ".worktrees", "node_modules", ".venv", ".driver-state", "__pycache__", ".pytest_cache"}

# dev-sessions/ and archive/ are frozen by design: their *content* is a historical
# record and is not maintained. Their links must still resolve, so they are
# link-checked but exempt from freshness checks.
FROZEN = ("docs/archive/", "docs/dev-sessions/")

failures: list[str] = []
skips: list[str] = []


def under_nested_worktree(p: Path) -> bool:
    """True if any directory strictly between ROOT and `p` carries a `.git` entry.

    A linked git worktree's root holds `.git` as a *file* (`gitdir: …`); a nested
    clone or submodule holds it as a *directory*. Either one marks a working tree
    that is not this one -- whatever it is named, and wherever the tool that made
    it decided to put it.

    That last part is why this is a marker and not another name. `md_files()` used
    to decide what was a worktree by matching directory names, and no name list can
    be right: `.worktrees/` is the fallback this repo never uses, while Claude Code
    actually creates them at `.claude/worktrees/`. Enumerating spellings is the
    hand-maintained-inventory shape issue #50 argued against; this identifies the
    class instead. Stdlib only, no subprocess.

    **ROOT is excluded from the walk, and that is a requirement rather than an
    optimisation.** ROOT always carries a `.git` entry of its own -- a directory in
    a main checkout, a file in a worktree -- so a rule that included it would skip
    everything and reintroduce #62's original bug through its own fix. Guard G4
    exists for exactly this. Walking the *relative* parts is what makes the
    exclusion structural: it cannot climb above ROOT and find the repo's own `.git`.
    """
    d = ROOT
    for part in p.relative_to(ROOT).parts[:-1]:
        d = d / part
        if (d / ".git").exists():
            return True
    return False


def md_files() -> list[Path]:
    """Every maintained markdown file under ROOT.

    Exclusions are matched against each path **relative to ROOT**, never against
    its absolute components. Matching absolutely means a directory can exclude
    *itself*: run from `.worktrees/<branch>/` and ROOT's own path carries
    `.worktrees`, so every file beneath it matched and the checker scanned nothing
    while still exiting 0 -- a null rendering as a pass, in the one detector built
    to catch that shape. See issue #62.

    Two rules, and they are not redundant. `SKIP_DIRS` still excludes by name, which
    is what catches a bare `.worktrees/` or `node_modules/` holding no checkout of
    its own; `under_nested_worktree()` excludes by marker, which is what catches a
    real worktree at a path no name list happened to mention.
    """
    out = []
    for p in ROOT.rglob("*.md"):
        if any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts):
            continue
        if under_nested_worktree(p):
            continue
        out.append(p)
    return sorted(out)


def is_frozen(p: Path) -> bool:
    rel = p.relative_to(ROOT).as_posix()
    return rel.startswith(FROZEN)


# --- check 1: links ---------------------------------------------------------

def check_links() -> None:
    for p in md_files():
        text = p.read_text()
        for m in re.finditer(r"\]\(([^)#]+?)(#[^)]*)?\)", text):
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = (p.parent / target).resolve()
            if not resolved.exists():
                rel = p.relative_to(ROOT)
                failures.append(f"{rel}: link does not resolve -> {target}")


# --- check 2: table integrity ----------------------------------------------

def check_tables() -> None:
    """A table row must belong to a table that has a header separator.

    Catches the shape that actually happened: prose inserted between rows, so the
    rows after it form a new block with no `|---|` and render without headers.
    """
    for p in md_files():
        lines = p.read_text().split("\n")
        in_fence = False
        block: list[int] = []

        def flush(block: list[int]) -> None:
            if not block:
                return
            head = lines[block[0]]
            sep = lines[block[1]] if len(block) > 1 else ""
            if not re.match(r"^\|[\s:|-]+\|?\s*$", sep):
                rel = p.relative_to(ROOT)
                failures.append(
                    f"{rel}:{block[0] + 1}: table block has no header separator "
                    f"(orphaned rows render without headers) -> {head[:60]}..."
                )

        for i, line in enumerate(lines):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            if line.startswith("|"):
                block.append(i)
            else:
                flush(block)
                block = []
        flush(block)


# --- check 3: derivable counts ---------------------------------------------

def live_bash_assertions() -> int | None:
    try:
        env = dict(os.environ)
        env["AGENT_SESSIONS_GATE_TEST_WIRING_INNER_RUN"] = "1"
        r = subprocess.run(["uv", "run", "pytest", "--collect-only", "-q", "driver/test_*.py", "scripts/test_*.py"],
                           capture_output=True, text=True, cwd=ROOT, timeout=10, env=env)
        if r.returncode not in (0, 5):
            return None
        counts = re.findall(r":\s*(\d+)$", r.stdout, re.MULTILINE)
        if counts:
            return sum(int(c) for c in counts)
        return None
    except (OSError, subprocess.TimeoutExpired):
        return None


def check_counts() -> None:
    """Any '<N> assertion(s)' claim in a maintained doc must match the suite."""
    actual = live_bash_assertions()
    if actual is None:
        skips.append("assertion counts: could not run make gate-test "
                     "(NOT verified -- this is a skip, not a pass)")
        return

    # Known limitation, stated rather than hidden: this matches a literal and
    # cannot tell a *claim* from an *example*. On its first run it flagged
    # CLAUDE.md's own illustration of the bad pattern. Teaching it to ignore
    # quoted text would open a bypass -- a real stale claim in quotes would slip
    # through -- so the convention is instead to write examples with `N` rather
    # than a number. That is the inert-content false-positive class
    # (docs/findings.md defect class 5) landing inside the rot detector itself.
    pattern = re.compile(r"\b(\d+)[\s-]assertions?\b")
    checked = 0
    for p in md_files():
        if is_frozen(p):
            continue
        for n, line in enumerate(p.read_text().split("\n"), 1):
            for m in pattern.finditer(line):
                claimed = int(m.group(1))
                checked += 1
                if claimed != actual:
                    rel = p.relative_to(ROOT)
                    failures.append(
                        f"{rel}:{n}: claims {claimed} assertions; the suite reports "
                        f"{actual}. State the command, not the number."
                    )
    if checked == 0:
        # Not a failure -- but say so, so "no output" cannot be read as "verified".
        print(f"  (no assertion-count claims found to check; suite reports {actual})")


# --- check 4: partition path integrity ---------------------------------------

def is_shim(p: Path) -> bool:
    """True if `p` is a re-export shim (e.g. < 30 lines re-exporting from src/)."""
    if not p.is_file():
        return False
    try:
        content = p.read_text()
        if "Shim re-exporting" in content or (len(content.splitlines()) < 30 and "from agent_sessions" in content):
            return True
    except OSError:
        pass
    return False


def check_partition() -> None:
    """Assert every path named as a risk-gated or drivable partition item exists and is not a re-export shim."""
    claudemd = ROOT / "CLAUDE.md"
    if not claudemd.exists():
        return
    text = claudemd.read_text()
    lines = text.split("\n")
    in_target = False
    section_lines = []
    for line in lines:
        if line.startswith("## Risk-gated paths") or line.startswith("### Drivable"):
            in_target = True
            continue
        elif line.startswith("## ") and in_target:
            in_target = False
        if in_target:
            section_lines.append(line)

    for line in section_lines:
        stripped = line.strip()
        if stripped.startswith(("-", "*")):
            subject_part = re.split(r"\s+[—–-]+\s+", stripped)[0]
            backticks = re.findall(r"`([^`]+?)`", subject_part)
            if backticks:
                bt = backticks[0]
                bt_clean = bt.split(":")[0].strip()
                if not bt_clean or " " in bt_clean or bt_clean.startswith("--") or bt_clean.startswith("http"):
                    continue
                if bt_clean in ("Makefile", "docs/", ".github/**", "skills/**", "driver/", "scripts/"):
                    p = ROOT / bt_clean.replace("/**", "")
                    if not p.exists():
                        failures.append(f"CLAUDE.md partition path does not exist -> {bt_clean}")
                    continue

                if "/" in bt_clean or bt_clean.endswith((".py", ".sh", ".md")):
                    resolved = ROOT / bt_clean
                    if not resolved.exists() and not list(ROOT.glob(bt_clean)):
                        failures.append(f"CLAUDE.md partition path does not exist -> {bt_clean}")
                        continue
                    if resolved.is_file() and is_shim(resolved):
                        failures.append(
                            f"CLAUDE.md risk partition names a re-export shim path ({bt_clean}). "
                            f"Name the underlying implementation in src/agent_sessions/ instead."
                        )


def main() -> int:
    check_links()
    check_tables()
    check_counts()
    check_partition()

    for s in skips:
        print(f"  SKIP  {s}")
    for f in failures:
        print(f"  FAIL  {f}")

    if failures:
        print(f"\ndocs-check: {len(failures)} problem(s)")
        return 1
    print(f"docs-check: links resolve, tables well-formed, counts match"
          f"{' (with skips above)' if skips else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
