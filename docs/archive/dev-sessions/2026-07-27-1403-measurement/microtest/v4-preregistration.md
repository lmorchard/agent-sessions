# v4 — pre-registered before any v4 rep was run

Written and committed before running a single v4 rep, because I have now revised this
instrument twice and the next revision would be indistinguishable from tuning it until it
says what I want.

## Why v4 exists

v1–v3 are forced-choice (`FREEZE-AS-WRITTEN` / `REPLACE-CHECK` / `CLOSE-AS-STALE`) and all
three rounds are contaminated by the same defect: reps whose *reasoning* is correct pick a
label that contradicts it. Tv3-3 ends "the oracle cannot discriminate 'done' from
'untouched'" — verbatim the `REPLACE-CHECK` assertion — and answers `CLOSE-AS-STALE`. Adding
explicit `Asserts:` clauses in v3 reduced this but did not remove it. A label a correct chain
of reasoning cannot reliably land on is a broken instrument, per this project's own rule.

v1–v3 still yield one clean number, because `FREEZE-AS-WRITTEN` has no such ambiguity: no
correct reasoning path lands on it by accident. That number is reported with the rest.

## What v4 tests instead

The discriminate rule has two halves, and v1–v3 only touch one:

1. **Interpretation** — "a check that already passes proves nothing." v1–v3 test this by
   handing the model a green transcript.
2. **Procedure** — run the check and confirm it fails *before* freezing it. This is the half
   that actually failed in the #638 dogfood: the vacuous check was never run, it was assumed.

v4 tests the procedure half. No drafted criterion, no transcript, no verdict labels. The
model is asked to do what `intake` does — write the criteria section that will be frozen —
from the issue text alone, with no repository access.

## Arms

Unchanged: **Z** (no guidance), **C** (acceptance-criteria.md minus the discriminate rule),
**T** (acceptance-criteria.md as shipped). 5 reps each.

## Grading rubric — fixed now, applied after

Every rep read by hand, scored on three binary marks:

- **VALIDATE-FLAGGED** — the output states, for at least one criterion, that its check must
  be *run and observed failing* (or validated against current behavior) before it is frozen.
  A generic "verify the criteria" with no reference to observing a failure does NOT count.
  This is the primary metric.
- **VACUOUS-PROPOSED** — the output proposes `-W error::DeprecationWarning`, `filterwarnings
  = error`, or any other promote-warnings-to-errors invocation as the check for a
  *criterion* (not a guard). This is the exact check the real #638 intake nearly froze.
- **GUARD-SPLIT** — the output separates regression guards from criteria. Expected to be
  high in C and T (both carry the guards section) and low in Z; included as a
  manipulation check that the guidance file is being read at all.

## What each outcome would mean, decided in advance

- **Z low, C low, T high** on VALIDATE-FLAGGED → the discriminate rule earns its place. Keep.
- **Z low, C high, T high** → the concept is already reachable from the guards section; §2
  restates it. Trim §2 to the procedural sentence.
- **Z high, C high, T high** → the model supplies the procedure unprompted. Cut §2.
- **No arm high** → the rule does not transmit at all as written, which is a rewrite signal,
  not a keep signal.

VACUOUS-PROPOSED is diagnostic, not decisive: proposing the vacuous check is only a failure
if it is proposed *and* frozen without validation.
