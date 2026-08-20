# Notes — move 5

Full measurement account: [`microtest/results.md`](microtest/results.md). This file is the
session's own findings — the things that are not in the results table.

## The headline, stated plainly

`acceptance-criteria.md`'s "### 2. Does it discriminate?" is **deleted**. It measured *worse than
its own absence*: 15/15 on the target action without it, 8/15 with it (p ≈ 0.006), and the same
15/15 vs 8/15 when `intake.md` was added to the context. The failure it exists to prevent —
freezing a check you just watched pass — happened **once in 125 forced-choice reps**, and that one
came from a *variant* of the rule rather than from its absence.

## The most useful thing I learned: my judgment picked the harmful edit

Partway through, the evidence supported trimming § 2 rather than cutting it. The trim I designed —
keep the heading and "Run the check and confirm it fails on current behavior.", drop the two
elaborating paragraphs — was smaller, needed no cross-file edits, and preserved the "three tests"
structure. It looked obviously right.

Measured as **arm M, it was the worst of all nine arms (2/15)** and the only arm in the entire
study that ever produced `FREEZE-AS-WRITTEN`. A bare instruction to run the check, stripped of its
elaboration, appears to license *"I ran it, it's green, done."*

I would have shipped it. The only reason I did not is that arm M cost about $5 and twelve minutes,
and by then the session had established that running the thing beats reasoning about it. **That is
the same lesson as move 4c's guards — "I wrote a guard" is not evidence — applied one level up to
wording: "this trim is obviously safe" is not evidence either.**

A related discipline that paid off: I formed a mechanism hypothesis (§ 2's "the issue is stale"
branch was attracting the wrong verdict), and instead of writing it into the design doc as an
explanation, built arm P to test it. **It was wrong** — P scored identically to the untouched file.
Two more attribution arms (R, N) also failed to explain the effect. The mechanism is recorded as
*unknown*, which is worth more than a plausible story would have been.

## The instrument rule needs sharpening, and the handoff's version is not enough

The handoff says verdict labels must **name actions, not intents**. I followed that and it still
failed twice: `CLOSE-AS-STALE` names an action perfectly well, and 14/15 reps chose it while their
own reasoning argued against it. Tv2-4, in full contradiction of itself:

> "The second run without that flag shows the 2 warnings are still present … This means the
> behavior the issue asks for has already been implemented."

What fixed it was making the labels **disjoint on evidence** — each label stating what choosing it
*asserts about the world*, so a correct chain of reasoning cannot satisfy two of them:

```
REPLACE-CHECK   Asserts: this check would report the same result whether or not the work is
                done, so it cannot grade it.
CLOSE-AS-STALE  Asserts: the symptom this issue reports is no longer present in the repository.
```

Even that only reduced the leak rather than removing it. **Proposed successor to the rule:
verdict labels must be disjoint on evidence — two labels a single observation can satisfy will
be chosen by vibe.** Recorded here and in `design.md`, deliberately *not* added to the skill: it
is an instrument-design rule for micro-tests, not a rule any mode reads, and this session's whole
finding is about the cost of adding text nobody measured.

## Reading every rep by hand is where all the value was

Every real finding came from reading outputs, never from the tally:

- The v2 label magnet is invisible in the counts (14/15 for one label looks like consensus) and
  obvious in the prose.
- Arm C's reps reproduce the deleted rule's own reasoning unprompted, which is what "redundant"
  actually looks like.
- The no-guidance arm never proposed the vacuous `-W error` check in v4 — it went straight to
  `make test` → 0 warnings, which is the check the real #638 intake landed on after a dogfood
  failure.

A tally-only reading of this study would have concluded "the rule works, 8/15 beats 2/5" and kept it.

## Two small process failures worth naming

- **The tally script scored a real verdict as `other`** because some reps emit a leading blank
  line and it took `head -1`. Found by chasing a single anomalous cell. A counting bug that
  silently undercounts is exactly the class of thing this project keeps writing down — a null
  must never render as a positive.
- **v4's primary metric was suppressed by my own prompt.** The seal says "you cannot run
  commands", which forecloses "run the check before freezing" — the very thing v4 was built to
  measure. Recorded as a null with the cause named, not as a finding.

## On the intake, and a criterion that over-constrained its own oracle

`intake` on decafclaw **#668** (items 1 + 3; item 2 split to **#718**) landed `auto-ok` and gave
the loop its second vehicle — `make dry-run` reports `eligible: 2` for the first time.

Then the driver run on #668 hit the **amendment path**, which had been unexercised across six
prior runs and which the handoff explicitly said not to manufacture a case for. It fired on its
own, and it fired on wording *I* wrote. C2's check specified the test's **mechanics** —
"mutates `_rawText`" — rather than only its assertion. The implementation needed a dirty flag that
direct state mutation does not set, so the frozen test did not exercise the criterion it named,
and the run had to reason about clarification vs amendment.

**The generalisable part: a criterion that names how the test manipulates state over-constrains
the oracle.** It is the same shape as move 1's lesson that a tamper rule stated as a whitelist of
allowed line forms produces false positives — state the invariant, not the mechanism. I wrote C2's
mechanics in to make it non-gameable, and traded one failure mode for another. Not added to the
skill as a rule: it is one instance, and the last three rules added on exactly this feeling were
all measured away.

## The two-issue loop: ran, and was not clean

Both issues reached `gate-eligible` (#668 → PR #719 at $11.76, #656 → PR #722 at $11.20). Both
would have exhausted the old $12 ceiling.

**#656 was recorded `failed` and parked, and it had actually succeeded.** Its stream carried a
successful result with the full merge-gate verdict, then a spurious `error_during_execution`, so
`claude -p` exited 1 — and the driver's `rc != 0` branch declared failure without ever looking at
the PR, four lines below a comment stating that the exit code is not the oracle. Move 4c fixed
that same spurious record in the *cost* field and did not carry the fix across to the exit code.
Fixed, mutation-tested, and #656 recovered with `--classify-only`.

The second defect is the more interesting one: the CI staleness check anchored the sha on a
literal `@`, and #722's run wrote `on f42c0f1`. Correct sha, wrong delimiter, **check silently
skipped** on a PR about to be called eligible. Everything downstream looked identical to a
verified-current row. This is the first time the thing that silently became a no-op was the
*verifier* rather than a value — previously it was `clean` hiding an absent diff or a truncated
board read.

**A guard I nearly shipped non-discriminating.** For the sha fix I first wrote the obvious test:
the #722 string parses and is judged *current* against its real head. It passes with the fix and
**also passes without it** — an unparseable sha yields "current" too. Only the paired
judged-*stale* case discriminates. Same trap as move 4c's `Edit(...)`-matches-`NotebookEdit`
guard, caught this time only because the mutation run is now habit.

## What the next session should not have to rediscover

- **§ 2 is gone and should stay gone.** Before re-adding anything about discrimination, read
  `microtest/results.md`; the trim that looks obviously safe is measured worst.
- **`build-variants.py` is now historical.** It derives its arms from `acceptance-criteria.md` by
  anchored deletion, and the anchors are gone. It will die loudly, which is the intent. The
  as-shipped file it measured is preserved as `microtest/guidance-T-as-shipped.md`.
- Each rep costs about **$0.33** and one arm of 15 takes roughly twelve minutes. A three-arm round
  is ~$15. That is cheap enough that "measure it" beat "reason about it" every time this session.
