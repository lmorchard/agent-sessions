# Session notes — #12, the freeze-time check-reviewer

**2026-08-01. Human-run, not drivable** (`skills/**` is risk-gated). Issue
[#12](https://github.com/lmorchard/agent-sessions/issues/12); option 1 narrowed, ratified by Les
before this session. No interview here — implementation plus dogfood.

## What was built

The missing third role. `frozen-checks.md` already separated a **check-author** (never sees the
plan) from a **verifier** (never sees the plan or the rationale, runs at the end of `execute`).
Nothing read the checks between writing them and locking them.

- **`references/frozen-checks.md`** — freeze step 4 is new: dispatch a read-only check-reviewer,
  given `checks.md` and the repo, never the plan and never the criteria's rationale; remit is one
  question per check and per guard, `acceptance-criteria.md` § 2's existing gameability test
  asked by a context that did not write the check. Result recorded under a new `## Adjudication`
  section, one disposition per check *including the cleared ones* — a cleared check and an
  unreached check are otherwise the same silence. Step 5 (commit) now states that the freeze
  commit closes the review window, and that the adjudication record sits inside the tamper
  baseline. A paragraph under **Independent verification** says plainly that the reviewer and the
  verifier are different dispatches and must not be merged.
- **`phases/plan.md`** step 5 — the dispatch in the freeze sequence, with the reason it precedes
  the commit: it is the last point at which a weak check is cheap to fix.
- **`references/plan-template.md`** — the Phase 0 checkbox.

Strengthening a check at step 4 is deliberately **not** an amendment and costs no tier: nothing
is frozen yet. That is the whole reason the step sits where it does.

## The dogfood — C1 met, C2 not met

Fixture design and the seeded check are documented in [`dogfood/README.md`](dogfood/README.md).
Two rounds, three independent read-only reviewers each, six reps total. Every rep read by hand.

**Recall — 6/6.** Every rep escalated the seeded C1 and named the exact cheapest cheat.

**Precision — 0/6.** Every rep flagged every check, in both rounds. C2 requires the reviewer
report the seeded check *and not the others*, so **C2 is not met.**

**But the flags are correct**, which is the finding. Reading them by hand:

- Round 1's non-seeded checks came from #62's already-triaged body. `make gate-test` genuinely
  does not detect a deleted or skipped case; `all checks passed` genuinely is an unconditional
  `@echo` that survives dropping a prerequisite; "non-zero file count" genuinely is satisfied
  by 1. The fixture could not distinguish *the reviewer flags everything* from *everything here
  is flaggable* — a non-discriminating instrument, so it was rebuilt rather than reported.
- Round 2 tightened all four guards using round 1's findings, verified each by running it. The
  reviewers found a **new, verified, decisive** hole anyway: every guard reads `SKIP_DIRS` from
  the module rather than from a roster frozen in the manifest, and this checkout has no `*.md`
  under any skip dir — so `SKIP_DIRS = set()`, deleting the exclusion feature outright, greens
  **all five checks**. Two reviewers confirmed it in-process independently. They also found that
  C1 and G2 cannot both be green as frozen (C1's new test makes `gate-test` 114; G2 pins 113).

Round 2's prompt said explicitly that `accepted` is a real and expected outcome and not to
manufacture findings. Still 0 accepts. That rules out prompt pressure as the explanation.

Three unseeded defects were found that the author did not know were there: the `0 failed` string
pytest never prints, the read-only self-contradiction, and the `SKIP_DIRS` mutation. Two rounds
of deliberate hand-tightening by the author did not find the third.

## What this means, and the open question for Les

**The mechanism works — better than C2 anticipated.** *"The verifier catches its author"* now has
a fifth instance and its first at *freeze* time rather than after implementation.

**C2 may be the wrong criterion.** It presupposes a manifest whose non-seeded checks are not
satisfiable without the work. Two rounds could not produce one, and the second round's failure
was found by the reviewers rather than by the author — so the presupposition, not the reviewer,
is what did not hold. C2 should probably be restated as a *ranking* property (the seeded check is
the one escalated unanimously — true in both rounds) rather than an all-clear property.

**The real design risk, which is Les's call and was not gated away silently.** If every freeze
returns five findings, the freeze gets expensive and the operator learns to wave the section
through — the exact *"false positives train the operator"* failure `findings.md` names. Except
these are not false positives, which is what makes it hard. Options, none taken unilaterally:

1. **Ship as-is.** Record the finding; let the adjudication records accumulate and see whether
   the volume is real or an artifact of a fixture built to be reviewed.
2. **Add a disposition bar** — only `escalated` blocks the freeze; `strengthened` is advisory.
   This is a behaviour-shaping wording addition, and this project is 3-for-3 on those measuring
   away. I would not add it without evidence.
3. **Reconsider scope** — e.g. reviewer sees criteria only, not guards. Guards drew 3/3
   `strengthened` in round 2 and none of that is about the criterion being graded.

My recommendation is **1**, and to let the sequencing decision the issue already made do its
job: the adjudication records are the evidence for what to build next.

## Verification

`make check` green before commit. `make skill-readonly` (G1) green — load-bearing here, since the
entire deliverable is `skills/**`. `python3 scripts/docs_check.py` (G2) exit 0, run from the repo
root, not from a worktree ([#62](https://github.com/lmorchard/agent-sessions/issues/62) means a
worktree run would scan nothing). G3's invariant holds: no check lost, newly skipped or newly
failing; the driver suite is **113**, which is above the guard's floor — the floor is the
invariant and was deliberately not "updated".

## Correction to the handoff

`main` is at `e370370`, but the working tree was **clean** at session start, not dirty: the
README / `design.md` / `orientation.md` work had already been committed as `1dc963e` on
`docs/orientation-onramp` and opened as PR #64.
