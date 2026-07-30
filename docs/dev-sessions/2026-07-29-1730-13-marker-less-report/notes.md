# Session notes — #13, report marker-less issues

**Run:** unattended `agent-session express`, 2026-07-29, no human watching.
**Outcome: PARKED at the amendment gate. No PR opened. Nothing merged.**

## Where it stopped, and why

The implementation is complete and **all three of C1's frozen assertions pass**, as does G1. The
run stopped because a **different** assertion in the frozen check file fails — the liveness probe
the check-author added alongside C1:

```bash
check "probe: the stub served both issues to the select stage" \
  "repo stub/repo: read 2 open issues" \
  "$(printf '%s\n' "$M_OUT" | grep '^repo stub/repo:' || true)"
```

`check()` is exact equality (`test-driver.sh:18`). The probe therefore pins the **whole** count line
— and the spec's design decision requires changing exactly that line:

> **Decision:** the report is a parenthetical appended to the existing `read N open issues` line, as
> the body proposes. […] **Rejected:** a separate line.

So the frozen check and the frozen spec are in direct conflict. Observed, after implementing what the
spec prescribes:

```
select: a mixed queue must account for its marker-less issues
  FAIL  probe: the stub served both issues to the select stage
     expected: repo stub/repo: read 2 open issues
     actual:   repo stub/repo: read 2 open issues (1 carry the marker; 1 do not: #6964 -- run triage)
  ok    (a) the marker-less issue number appears in select output
  ok    (b) no ELIGIBLE line names the marker-less issue
  ok    (c) the run still reports one eligible issue
select: the zero-marker message is not swallowed by partial reporting
  ok    G1 an all-marker-less queue still says no issues carry the marker

68 passed, 1 failed
```

The produced line is exactly the shape the issue body asked for. Any implementation that satisfies the
design decision fails this probe; no implementation satisfies both.

## Why this is an amendment and not a clarification

Applying `frozen-checks.md`'s mechanical test to the obvious repair (narrow the probe from exact
equality to containment), against **both** trees:

| | at freeze (`8438711`) | vs. implementation (`3597ad0`) |
|---|---|---|
| old probe (exact equality) | passes — observed in the freeze run | **fails** — observed above |
| new probe (containment) | passes — the exact string *is* the whole line there | passes — it is a prefix of the new line |

Verdict **same** at freeze, **differs** against the implementation. That is the bottom-left cell of
`frozen-checks.md`'s table: **amendment.** Which means human confirmation, a logged amendment, and a
**tier downgrade to `needs-review` for this run**.

(The freeze-tree row for the new probe is reasoning, not a run: confirming it by execution would mean
editing the frozen file, which is the thing being asked about. The basis is string containment against
a line recorded verbatim in `checks.md`.)

## The decision that needs a human

Two coherent options. Neither is mine to take.

**Option 1 — amend the probe** (narrow it to containment / prefix), keep the spec's prescribed output.
Cost: a logged amendment and this run downgrades to `needs-review`.

**Option 2 — override the design decision**: emit the report on its own line, leaving the count line
byte-identical. Then the probe passes untouched, no amendment is needed and the tier stays `auto-ok` —
but the run has silently ignored a recorded design decision, which is its own failure shape.

**Recommendation: Option 1.** The probe is the weaker artifact. It was authored by *this run's own*
check-author subagent an hour ago, as liveness scaffolding, and it is not one of the three assertions
the issue froze — the CHECK text names (a), (b), (c) and nothing else. Its defect is specific and
narrow: a liveness probe needs to know the driver *reached* the select stage, which containment
establishes; exact-equality additionally pins a line the spec says to change, and that extra strictness
buys no liveness signal. Meanwhile the design decision is the older, independently-authored artifact
and the issue author's explicit request. Option 2 costs less procedurally and more substantively, and
"cheaper because nobody has to approve it" is the wrong reason to pick a branch here.

Note the downgrade is close to free in this instance: the run is already stopping for a human, so
Option 1 adds a signature, not a lane change.

## What was verified, and what wasn't

Stated plainly so nothing reads as green that isn't:

- **Tamper diff on the frozen check file: clean.** `git diff 8438711 -- driver/test-driver.sh` is
  empty. The check was not touched, relaxed, or narrowed — the failing probe is failing as authored.
- **`driver/gate.py` untouched**, so the tier's stated contingency did **not** fire and the
  `auto-ok` derivation still stands on its stated basis.
- **G4 discharged.** The issue flagged it UNRUN and required it be run once before merge. `make check`
  was run at session setup, before any edit: full pass, `driver-test` 64/0, `park-test` 21/0. That is
  the pre-edit baseline.
- **G2 discharged by proxy, not invoked.** This run's sandbox refused direct interpreter invocation, so
  the literal `printf | python3 driver/gate.py tier-batch` pipeline never ran. Substitutes:
  `test_gate.py:237` asserts the same property, `test-driver.sh:133-135` drives the same CLI, and the
  path half is covered by the diff above. Recorded as *discharged by proxy* rather than *passed*.
- **`make check` is NOT green** and was not run to completion after the implementation — `driver-test`
  fails on the probe, which fails `make check` by construction.
- **No independent verifier subagent was dispatched** (express 2d). Deliberate: the run stopped at
  2a/2c on an amendment, before verification. Dispatching a verifier now would produce a report on a
  tree whose oracle is under dispute.

## Two things worth carrying forward

1. **The live-board form would now pass with zero code change.** The spec refused to freeze
   "invoke `--repo lmorchard/agent-sessions --dry-run` and assert #11 and #12 appear," on the grounds
   that a triage pass could make it green for free. That is exactly what happened: as of this run there
   are 15 open issues and **all 15 carry the marker** (`gh issue list` verified). The rejected check
   would be green today against unmodified code. Good call, and a clean vindication of the
   satisfiable-without-the-work test.

2. **The jq complement had the bug it was reporting on.** First attempt used
   `select(([$k[]] | index(.)) == null)`. In `index(f)`, `f` is evaluated against `index`'s own input,
   so `.` was the keep-list, not the number; it matched every time and the complement came out empty —
   a reporter that unconditionally says "nothing missing." It produced a *passing-looking* run with the
   count line unchanged, and I nearly read that as evidence about the probe conflict instead of as my
   own defect. Caught only by running it. Same defect class as the issue itself
   (`findings.md` class 2), reproduced inside the fix for it.

## Housekeeping

- A stray `tmp/probe13.sh` was created in the worktree early on (a scratch probe, superseded by the
  frozen test). The sandbox denied `rm`, so it is still there, **untracked and never staged** — every
  commit in this run used explicit paths, never `git add -A`, per this repo's own lesson in `f26e63a`.
  It needs deleting by hand.
- Board: issue #13 was moved to **In progress** at setup and left there. Parking/labelling is the
  driver's job, not the skill's.
