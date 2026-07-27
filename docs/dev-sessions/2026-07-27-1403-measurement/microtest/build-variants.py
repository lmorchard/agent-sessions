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
OUT_P = pathlib.Path(__file__).resolve().parent / "guidance-P-pruned.md"

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

# --- arm P: the proposed trim ------------------------------------------------------------
#
# Arm C answers "does the rule earn its place?"; arm P answers "does one specific sentence of
# it make things WORSE?". Two sentences come out and nothing goes in:
#
#   "A check that already passes proves nothing -- it will still pass if the implementer
#    changes nothing at all. Either the behavior is already there (the issue is stale) or the
#    check isn't testing the criterion."
#
# Sentence one is measured redundant: 45/45 reps across v1-v3, including the no-guidance arm,
# produced that reasoning unprompted and not one froze a check it had watched pass. Sentence
# two offers "the issue is stale" as the first of two branches, and it is the branch every
# mis-labelled rep took -- including three treatment reps whose own text said the check could
# not grade the work. This variant exists to test that mechanism instead of asserting it.
pruned = SRC.read_text()
pruned = sub(
    pruned,
    "**Run the check and confirm it fails on current behavior.** A check that already passes proves\n"
    "nothing — it will still pass if the implementer changes nothing at all. Either the behavior is\n"
    "already there (the issue is stale) or the check isn't testing the criterion.\n",
    "**Run the check and confirm it fails on current behavior.**\n",
)
OUT_P.write_text(pruned)
print(f"wrote {OUT_P}  ({len(SRC.read_text().splitlines())} -> {len(pruned.splitlines())} lines)")

# --- arms R and N: attribution -----------------------------------------------------------
#
# C (whole section removed) scores 15/15 and T (as shipped) 8/15, p ~ 0.006. P shows the
# branch-enumeration sentence is not the cause. Section 2 has two paragraphs left that could
# be, and they imply very different edits -- delete one paragraph, or delete the section. So
# each is removed on its own rather than reasoned about.
#
#   R  minus "Record the observed failure ..." -- suspected because it argues the issue's own
#      reported evidence may be stale ("the repo has moved"), which is an argument FOR the
#      wrong verdict on this fixture.
#   N  minus the near-miss paragraph -- the one that describes this exact case, and therefore
#      the one that should help most if any of it does.
RECORD_PARA = """
Record the observed failure. Evidence from a past run — a table in the issue, a number someone
remembers — is not a substitute for running it: the repo has moved, and the invocation that
produced that table may not be the one you wrote down.
"""

NEAR_MISS_PARA = """
Watch the near-miss: the *command* exists and runs, but can't reproduce the condition the
criterion is about. A benchmark invocation that omits the config where the problem appears will
report clean forever. The tell is a criterion phrased "SHALL produce zero X" whose command
produces zero X today.
"""

for name, para in (("R", RECORD_PARA), ("N", NEAR_MISS_PARA)):
    variant = sub(SRC.read_text(), para, "")
    out = pathlib.Path(__file__).resolve().parent / f"guidance-{name}-minus-para.md"
    out.write_text(variant)
    print(f"wrote {out}  ({len(SRC.read_text().splitlines())} -> {len(variant.splitlines())} lines)")
