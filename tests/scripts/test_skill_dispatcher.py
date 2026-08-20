"""Frozen acceptance checks for #261 K1 — the dispatcher lists every phase that exists.

`SKILL.md`'s dispatcher table is what an agent reads to find out which modes exist, and
`pr_checks.build_prompt` tells it to read `SKILL.md` and then the phase file. So a mode
missing from the table is a mode the agent lands in having just been told it does not
exist.

Two were missing: `fix_conflict`, which `reconciler.py` requests when a PR's branch has
diverged from its base, and `refine`, which `router.py` requests for every specced
`needs-review` issue. Both are phases the **driver actively selects** — not
human-invoked conveniences — so nothing a person did would have surfaced the gap.

This is a directory listing against a table, which is exactly the shape that goes stale:
adding a phase file is the natural act, and editing a table in another file is the one
that gets forgotten.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / "skills" / "agent-session"
PHASES = SKILL / "phases"

#: A dispatcher row: `| `mode` | `phases/mode.md` | purpose |`
_ROW = re.compile(r"^\|\s*`(?P<mode>[a-z_]+)`\s*\|\s*`phases/(?P<file>[a-z_]+\.md)`\s*\|", re.MULTILINE)


def _dispatcher() -> dict[str, str]:
    return {m.group("mode"): m.group("file") for m in _ROW.finditer((SKILL / "SKILL.md").read_text())}


def _phase_files() -> set[str]:
    return {p.name for p in PHASES.glob("*.md")}


def test_the_dispatcher_has_rows_to_check():
    """Control. Every check below passes vacuously over an unparsed table."""
    assert len(_dispatcher()) >= 5, _dispatcher()


def test_every_phase_file_appears_in_the_dispatcher():
    """C1. The defect: a phase the driver requests that the dispatcher denies exists."""
    missing = sorted(_phase_files() - set(_dispatcher().values()))
    assert not missing, (
        f"phase file(s) with no dispatcher row: {missing}. `pr_checks.build_prompt` sends the "
        f"agent to SKILL.md and then to the phase file, so it lands in a mode its own "
        f"dispatcher says does not exist."
    )


def test_every_dispatcher_row_points_at_a_file_that_exists():
    """C2, the other direction. An orphan row sends a run to a missing file."""
    orphans = sorted(f for f in _dispatcher().values() if not (PHASES / f).is_file())
    assert not orphans, f"dispatcher rows naming no phase file: {orphans}"


def test_each_row_names_the_file_matching_its_mode():
    """C3. `| `refine` | `phases/rethink.md` |` would satisfy both checks above."""
    mismatched = {m: f for m, f in _dispatcher().items() if f != f"{m}.md"}
    assert not mismatched, f"mode/file mismatches: {mismatched}"
