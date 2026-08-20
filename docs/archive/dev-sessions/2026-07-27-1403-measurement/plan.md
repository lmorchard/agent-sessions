# Plan

Deliberately thin. The measurement's shape could not be planned in advance — the instrument was
wrong twice and each correction changed what the next step was. What follows is the order the
work actually took, kept as a record rather than reconstructed as if it had been foreseen.

## 1. Micro-test the discriminate rule

1. Build the fixture **from the code**: check out decafclaw at `bd6cbf3` (base of PR #659, before
   the fix) and *run* the two pytest invocations. Extract #638's original author text from the
   live issue, stopping before the intake pass appended its criteria.
2. Derive the control by **anchored deletion from the shipped file**, not by hand-copying, so the
   arms cannot differ in more than the rule under test.
3. Run control vs treatment, ≥5 reps, from a neutral cwd so this repo's own docs cannot leak.
4. **Read every rep by hand.** Act on the result.

Steps 3–4 ran four times. v1 was under-determined; v2 exposed a label magnet; v3 fixed the labels
and is the round the numbers come from; v4 dropped forced choice entirely, with its rubric
pre-registered and committed before any rep ran. Arms P/R/N/M isolate sub-paragraphs; D/E re-run
the decisive pair with `intake.md` in context.

## 2. Unblock the two-issue loop

Only #656 was eligible, so a solo run would have consumed the only vehicle. `intake` on a second
issue first, then a single `--max-issues 2 --max-budget-usd 25` run over both.

## 3. Record

`design.md` build-status, this directory, and the deletion itself — the shipped file byte-identical
to the measured arm.
