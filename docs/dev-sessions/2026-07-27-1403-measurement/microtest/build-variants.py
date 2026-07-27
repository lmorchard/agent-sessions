#!/usr/bin/env python3
"""Derive the control variant of acceptance-criteria.md from the shipped file.

Deriving rather than hand-copying is deliberate: a hand-written control drifts from the
real file, and then the arms differ in more than the rule under test. Every deletion is
anchored on exact text and the script dies if an anchor is missing, so a future edit to
the shipped file breaks this loudly instead of silently changing what "control" means.

Arm C removes the discriminate rule (section 2) and ONLY the text that is meaningless
without it -- the section-count heading, the renumbering, the tier trigger's clause, and
the one sentence whose subject is "test 2". Text belonging to OTHER rules stays even
where it implies discrimination (notably the criteria-vs-guards section), because the
question this experiment asks is exactly whether the concept is already reachable there.
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[4]
SRC = ROOT / "skills/agent-session/references/acceptance-criteria.md"
OUT = pathlib.Path(__file__).resolve().parent / "guidance-C-no-discriminate.md"

text = SRC.read_text()


def cut(haystack: str, start: str, end: str) -> str:
    """Delete [start, end) -- start inclusive, end exclusive. Both must be unique."""
    i = haystack.find(start)
    j = haystack.find(end)
    if i < 0:
        sys.exit(f"anchor not found: {start!r}")
    if j < 0:
        sys.exit(f"anchor not found: {end!r}")
    if j <= i:
        sys.exit(f"anchors out of order: {start!r} .. {end!r}")
    if haystack.count(start) != 1:
        sys.exit(f"anchor not unique: {start!r}")
    return haystack[:i] + haystack[j:]


def sub(haystack: str, old: str, new: str) -> str:
    if haystack.count(old) != 1:
        sys.exit(f"replace anchor not unique ({haystack.count(old)}x): {old!r}")
    return haystack.replace(old, new)


# 1. The rule under test: the whole of section 2.
text = cut(text, "### 2. Does it discriminate?", "### 3. Can it pass without the work")

# 2. Renumber the surviving gameability section.
text = sub(text, "### 3. Can it pass without the work", "### 2. Can it pass without the work")

# 3. The section count in the heading and its lead-in list.
text = sub(text, "## Three tests every check must pass", "## Two tests every check must pass")
text = sub(text, "put its check through all three.", "put its check through both.")

# 4. The one sentence in the guards section whose subject is the deleted test.
text = sub(text, "Without this split, test 2 would reject legitimate checks. ", "")

# 5. The tier trigger's enumeration of the three tests.
text = sub(
    text,
    "or fails one of the three tests above (no\noracle, doesn't discriminate, satisfiable without the work)",
    "or fails one of the two tests above (no\noracle, satisfiable without the work)",
)

OUT.write_text(text)
print(f"wrote {OUT}  ({len(SRC.read_text().splitlines())} -> {len(text.splitlines())} lines)")
