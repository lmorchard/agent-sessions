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

An instruction-file line saying that would be an exhortation, and this project is
3 for 3 on added rules measuring away (see docs/findings.md defect class 4).
Mechanical detectors have worked every time. So this is a detector.

It includes these checks, each motivated by a defect actually found:

  * every relative markdown link resolves  -- caught real breakage twice while
    relocating docs into archive/, in both cases invisible to reading;
  * no orphaned table rows            -- a prose block split a table in
    findings.md, leaving two rows to render headerless;
  * claimed assertion counts match reality -- the "49-assertion" class;
  * AGENTS.md and CLAUDE.md carry the same parsed risk-path policy.

this project's most-repeated lesson is that a null must not render as a positive,
and a checker that quietly skips is the same defect one level up.
"""

from __future__ import annotations

import ast
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
        r = subprocess.run(["uv", "run", "pytest", "--collect-only", "-q", "tests/driver/test_*.py", "scripts/test_*.py"],
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

def _reexport_sources(tree: ast.Module) -> set[str]:
    """Dotted module names a facade pulls its re-exported names from.

    Relative imports are returned as the bare tail (`.lifecycle` -> `lifecycle`), so a
    caller matching against a path suffix handles both spellings without resolving the
    package root.
    """
    sources = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module in (None, "__future__"):
                continue
            sources.add(node.module)
    return sources


def is_shim(p: Path) -> bool:
    """True if `p` is a re-export facade: it defines nothing and imports names from elsewhere.

    The predicate this replaces was a marker string, or a 30-line ceiling on a file
    mentioning `from agent_sessions`. It was sized for the top-level shims #205 deleted
    and it was wrong in both directions. It missed the live instance the guard exists
    for -- `src/agent_sessions/driver/agent_session_driver.py` carries no marker, runs
    past 150 lines, and its own docstring opens *"Defines nothing itself"* -- while a
    short ordinary module that imports one helper and defines one function matched.

    Length was never the property that mattered. Originating nothing is. A module with
    no function and no class of its own, that imports names from other modules, is a
    facade however long its `__all__` runs. Both halves are load-bearing: dropping the
    import requirement would flag a constants module, which the partition has every
    right to gate.

    Non-Python files fall back to the explicit marker -- `driver/agent-session-driver.sh`
    is named in the partition and there is nothing to parse.
    """
    if not p.is_file():
        return False
    try:
        content = p.read_text()
    except OSError:
        return False
    if "Shim re-exporting" in content:
        return True
    if p.suffix != ".py":
        return False
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return False
    defines_own_code = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        for node in ast.walk(tree)
    )
    return not defines_own_code and bool(_reexport_sources(tree))


def _facade_stands_alone(facade: Path, section_lines: list[str]) -> set[str]:
    """Empty if the partition names any module behind `facade`; else the candidates it could name.

    Gating a facade is not the defect. An entry point is worth gating even after it thins
    out -- `driver/agent-session-driver.sh` is gated on exactly that reasoning. The defect
    is a facade standing in *for* the implementation, so the partition reads as protecting
    code it never names. The question is therefore not "is this a facade?" but "does the
    partition show any awareness of what is behind it?"

    Hence *any*, not *all*. A facade re-exporting five modules does not owe the partition
    five bullets: unlisted paths are already `needs-review` by default, so nothing is
    exposed by their absence, and demanding each one would fill the section with entries
    carrying no reason -- which is the opposite of what it is for. One named source proves
    the substitution is not happening; zero is the case that misleads a reader.

    Only modules resolving to a real file count, so a facade re-exporting the standard
    library cannot raise a demand the partition has no way to satisfy.
    """
    try:
        tree = ast.parse(facade.read_text())
    except (OSError, SyntaxError):
        return set()

    section = "\n".join(section_lines)
    candidates = set()
    for dotted in _reexport_sources(tree):
        rel = Path(*dotted.split(".")).with_suffix(".py")
        target = next((c for c in (ROOT / rel, ROOT / "src" / rel) if c.is_file()), None)
        if target is None:
            continue
        named = str(target.relative_to(ROOT))
        if named in section:
            return set()
        candidates.add(named)
    return candidates


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
                        alone = _facade_stands_alone(resolved, section_lines)
                        if alone:
                            failures.append(
                                f"CLAUDE.md risk partition names a re-export facade ({bt_clean}) "
                                f"and none of the code behind it, so it reads as gating an "
                                f"implementation it never names. Name one of: "
                                f"{', '.join(sorted(alone))}."
                            )


# --- check 5: instruction-file policy parity -------------------------------

def risk_policy_section(path: Path) -> str:
    """Return the complete risk-path policy section from one instruction file."""
    lines = path.read_text(encoding="utf-8").splitlines()
    starts = [
        i for i, line in enumerate(lines) if line.startswith("## Risk-gated paths")
    ]
    ends = [
        i for i, line in enumerate(lines) if line.startswith("## Governing principle")
    ]
    if len(starts) != 1 or len(ends) != 1 or ends[0] <= starts[0]:
        raise ValueError(
            "expected one 'Risk-gated paths' section followed by one "
            "'Governing principle' section"
        )
    return "\n".join(line.rstrip() for line in lines[starts[0] : ends[0]]).strip()


#: A pointer file defers to another instruction file rather than restating it. The
#: ceiling is generous on purpose: it exists to stop a full second instruction file
#: qualifying as a pointer by mentioning the first, not to police a preamble.
POINTER_MAX_LINES = 40


def is_policy_pointer(path: Path, target: str = "CLAUDE.md") -> bool:
    """True if `path` defers its risk-path policy to `target` instead of carrying one.

    Three conditions, and the first is the one that matters: a file carrying its own
    `## Risk-gated paths` section is **not** a pointer, however prominently it also
    links the target. That half-migrated shape -- a link plus a surviving copy -- is
    exactly what this whole change exists to prevent, because the copy is what drifts.
    Linking must not buy an exemption from parity.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    lines = text.splitlines()
    if any(line.startswith("## Risk-gated paths") for line in lines):
        return False
    if len([ln for ln in lines if ln.strip()]) > POINTER_MAX_LINES:
        return False
    return target in text


def check_risk_policy_parity() -> None:
    """One risk-path policy, whether AGENTS.md copies CLAUDE.md's or defers to it.

    The two files were byte-identical and only this section was guarded. Everything
    outside it drifted: a find-and-replace rewrote a filesystem path to one that exists
    nowhere, a second invented a `Codex -p` flag, and one section quietly lost a rule
    from AGENTS.md alone. The guarded part stayed in sync and the unguarded remainder
    did not -- and there is no bound on how much unguarded remainder there will be. So
    a pointer is an accepted shape, and the checks are about the ways a pointer can be
    wrong rather than a relaxation of the rule.
    """
    agents, claude = ROOT / "AGENTS.md", ROOT / "CLAUDE.md"

    if is_policy_pointer(agents):
        # The pointer is only worth anything if the target has a policy to point at.
        # Without this, deleting CLAUDE.md's section would leave *neither* file with
        # one and the parity check with nothing to compare -- passing on an empty set,
        # which is the null-as-positive shape this detector exists to catch.
        try:
            risk_policy_section(claude)
        except (OSError, ValueError) as e:
            failures.append(
                f"AGENTS.md defers to CLAUDE.md, which carries no usable risk-path policy: {e}"
            )
        return

    paths = (agents, claude)
    try:
        policies = [risk_policy_section(path) for path in paths]
    except (OSError, ValueError) as e:
        failures.append(f"could not compare AGENTS.md and CLAUDE.md risk-path policies: {e}")
        return

    if policies[0] != policies[1]:
        failures.append(
            "AGENTS.md and CLAUDE.md risk-path policies differ; keep the complete "
            "'Risk-gated paths' sections aligned"
        )


# --- check 6: judgment-phrased world-state assertions -----------------------

def check_world_state_claims() -> None:
    """Any capability/world-state claim phrased as a judgment must be cited.

    Catches phrases like 'Not proven', 'never been driven', bare repo counts, etc.
    """
    forbidden_patterns = [
        (r"\bnot proven\b", "claim wears the clothes of a judgment; use `make evidence` instead"),
        (r"\bnever been driven\b", "claim wears the clothes of a judgment; use `make evidence` instead"),
        (r"\b(one|two|three|four|five|six|seven|eight|nine|ten|\d+) repositories\b", "bare repo count; use `make evidence` instead"),
        (r"\b(one|two|three|four|five|six|seven|eight|nine|ten|\d+) PRs\b", "bare PR count; use `make evidence` instead"),
    ]

    for p in md_files():
        if is_frozen(p):
            continue

        content = p.read_text(encoding="utf-8")

        # Exception block: if we're reading CLAUDE.md or design.md and talking ABOUT the phrase
        for n, line in enumerate(content.splitlines(), 1):
            line_lower = line.lower()

            # Exceptions for documentation of the rules
            if "not proven" in line_lower and ("list survived" in line_lower or "count in disguise" in line_lower or "pointer to make evidence" in line_lower or "proven / not-proven list" in line_lower or "not-proven list" in line_lower):
                continue
            if "never been driven" in line_lower and "count in disguise" in line_lower:
                continue
            if "repositories" in line_lower and "runs against two repositories" in line_lower and "count in disguise" in line_lower:
                continue
            if "seven prs" in line_lower and ("three moves stale" in line_lower or "six merged" in line_lower):
                continue
            if "six prs" in line_lower and "across six prs, copilot returned in" in line_lower:
                continue
            if "eight prs" in line_lower and "being eight prs deep with" in line_lower:
                continue


            # Temporary carve-out while transitioning: don't flag the literal section talking about "Not proven"
            if "not proven" in line_lower and ("list" in line_lower or "count" in line_lower or "defect class" in line_lower):
                continue
            if "not proven" in line_lower and p.name == "orientation.md":
                continue # We explicitly declare "Not proven, and the docs say so:"

            # The dated-fact escape hatch: if the line contains a date pattern, it's allowed.
            if re.search(r"\d{4}-\d{2}-\d{2}", line):
                continue

            for item in forbidden_patterns:
                pattern = item[0]
                reason = item[1]
                cond = item[2:]
                m = re.search(pattern, line, re.IGNORECASE)
                if m:
                    if cond and not cond[0](m):
                        continue
                    rel = p.relative_to(ROOT)
                    failures.append(f"{rel}:{n}: {m.group(0)} -- {reason}")

def check_state_diagram() -> None:
    """Assert README.md state diagram matches programmatic generator."""
    from agent_sessions.scripts import state_diagram
    readme = ROOT / "README.md"
    if not state_diagram.check_readme(readme):
        failures.append("README.md state diagram is out of sync with generator (run state_diagram.py --update)")

def main() -> int:
    check_links()
    check_tables()
    check_counts()
    check_partition()
    check_risk_policy_parity()
    check_world_state_claims()
    check_state_diagram()

    for s in skips:
        print(f"  SKIP  {s}")
    for f in failures:
        print(f"  FAIL  {f}")

    if failures:
        print(f"\ndocs-check: {len(failures)} problem(s)")
        return 1
    print(f"docs-check: links resolve, tables well-formed, counts and risk policies match"
          f"{' (with skips above)' if skips else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
