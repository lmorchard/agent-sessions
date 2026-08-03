# Session notes — #58, the driver-fault false positive

Unattended `express` run, driven by the board-driver. 2026-08-03.

## What shipped

One helper, one tightened predicate, one conditional reason, all in
`driver/agent-session-driver.sh`'s classifier. The `driver-fault` branch now requires **positive
evidence** that the invocation never reached the model — an effectively empty stream — instead of
inferring it from two variables that are empty whenever `pick_result` misses. A truncated-stream
run falls through to `failed` with the cost named as undetermined.

The run is still parked and still stops the loop. What changed is the claim on the record.

## The freeze caught two real holes, both before the lock

Worth recording because this is the step whose value is hardest to see from the outside: the
check-reviewer is a dispatch that produces nothing when it works, and it is tempting to treat it
as ceremony. It was not ceremony here.

1. **C1's fixture leaked a second signal.** The stub emitted a `system/init` record carrying a
   `session_id`. That gave the fixture two things distinguishing it from G3's — events in the
   stream (the criterion's GIVEN) and a session id somewhere in the stream (not the criterion).
   A fix that scanned the whole stream for any `session_id` would have greened C1, kept G3 green,
   and left the criterion's actual case broken. Closed by removing the line and pinning the event
   count at exactly 2 with a `check` rather than a `>= 1` threshold — so the fixture's shape is
   now enforced by the suite instead of by a comment.

2. **C2's needle had no negative control.** Nothing stopped the implementer emitting
   `cost undetermined` unconditionally. That would have greened C2 and manufactured this very
   defect inverted: "cost undetermined" stamped onto the ledger row of a run whose cost was read
   perfectly well, with the real number sitting next to it. Closed by **G4**.

Both were found by a read-only reviewer that had not seen an implementation plan, because there
was no implementation plan yet — the ordering in `plan.md` step 5 is load-bearing, not tidy.

The check-author's initial report defended the `system/init` line on realism grounds and then,
given the reviewer's argument, retracted it explicitly rather than quietly. Recording that the
loop worked as intended.

## Checked rather than assumed

- **`--classify-only` does not duplicate the defect.** #5's C2 exists precisely because a
  duplicated parking case list got fixed at one site and not the other, so this was the obvious
  thing to get wrong. It forces `rc=0` and takes its outcome from the PR, so it has no
  `driver-fault` branch and makes no "no spend" claim. Left alone deliberately.
- **No existing assertion depended on the reason strings being changed.** Grepped both suites
  before editing.
- **`docs/usage.md`'s `driver-fault` row** — "the invocation never reached the agent" — needed no
  edit. It was already the correct description; the code is what disagreed with it.

## Known limits, stated rather than smoothed over

- **A malformed (unparseable) non-empty stream still classifies `driver-fault`.** `jq` exits
  non-zero, which `stream_has_events` reads as "no events". Deliberate and commented: it preserves
  today's behaviour for a case nobody has evidence about, rather than silently reclassifying it.
  The frozen check does not exercise it — the fixture's events are well-formed JSON.
- **`cost_known` is consulted in one branch only** (the nonzero-exit / no-success-result path).
  A run whose cost is equally undeterminable but which times out (rc 124) or reaches the gate
  records no such note. C2's CHECK exercises the path the implementation covers; widening it
  would be widening what a frozen criterion asserts, which is an amendment.
- **C2's negative half is substring-exact.** A reword to "no *recorded* spend" would slip past
  `hasnt "no spend"`. Left as the criterion's CHECK literally specifies; the weight is carried by
  the positive needle plus G4. Recorded in `checks.md`'s adjudication too.

## For a future session

- **Closing the race** (the issue's item 2): wait for the child to fully exit before reading its
  stream, so the flush is complete by construction. Deliberately out of scope here — the spec's
  Design decisions treat it as independent, and it would make this instance rarer without making
  the inference sound.
- **`cost_usd` as `null`/`unknown`** (item 3). Ruled out by the spec: `runs.jsonl` has readers and
  the type change is a wider blast radius than this issue's evidence supports.
- **`--classify-only`'s `say` line prints an empty cost** (`recovered from stream: cost $`) when
  the extractor misses. Not the same defect — it is a log line, not a ledger claim, and no
  criterion covers it — but it is the same shape and someone reading that output could draw the
  same wrong conclusion. Noted, not fixed; fixing it here would be scope creep.

## Housekeeping

Two scratch files (`repro58.sh`, `scratch-stream.jsonl`) were created early in the session to
re-confirm the issue's evidence, and are left **untracked** in the worktree. They are not
committed and do not ship. `rm` and `mv` are both outside the driver's `ALLOWED_TOOLS`, so they
could not be deleted from inside the run — worth knowing, since the obvious cleanup step is
unavailable to an unattended run and the files would otherwise look like an oversight.

## The governance question this run raises — for Les

The issue's Tier section flagged it at intake and it is the thing to actually decide:

`CLAUDE.md`'s risk-gated section names the exposure that `agent-session-driver.sh` contains the
outcome *routing*, declines to gate it (*"Path granularity cannot express 'this file except its
classification path'"*), and ends **"Revisit if a run ever touches that routing."**

This run touched that routing. It edited the branch that decides a run's own outcome — an
unattended run modifying the code that classifies unattended runs. The mitigations `CLAUDE.md`
relies on all held: the fixture suite caught the cheap fix (G3), the reviewer caught two ways to
fake the expensive one, `make check` is green, and there is a human at the merge gate. G3 and G4
exist specifically to block the self-serving versions of this change.

That is the second firing of the revisit clause (#39 was the first, and weaker — it edited a park
*reason*). **Whether the clause should now become a gate is a decision for Les**, not something
this run should resolve by analogy, and not something it should resolve at all given what it just
edited. `CLAUDE.md` was deliberately not touched by this run.
