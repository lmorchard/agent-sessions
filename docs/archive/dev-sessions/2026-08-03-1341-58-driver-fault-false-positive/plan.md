# driver-fault false positive — Implementation Plan

**Goal:** Stop the driver recording "no session, no spend" about a run whose cost it merely
failed to extract.

**Source issue:** https://github.com/lmorchard/agent-sessions/issues/58 — **Tier:** `auto-ok`
(every criterion is an assertion over a `runs.jsonl` row produced by the existing stub harness;
`driver/agent-session-driver.sh` is on CLAUDE.md's drivable allowlist and `driver/gate.py` is
untouched)

**Approach:** Fix the false inference; treat closing the race as separate work. The
`driver-fault` predicate infers "never started" from two empty variables, when what it actually
observed is "the extractor found nothing". Require **positive evidence** instead — an
effectively empty stream — and make the reason on the fall-through path say the cost is
undetermined rather than assert the run did not spend.

**Criteria:** C1 a stream with events but no `result` record is not `driver-fault` · C2 an
undetermined cost is reported as undetermined, not as "no spend"

Full text, checks and adjudication live in `checks.md`, frozen at `e3d3412`.

---

## Phase 0: Freeze the acceptance checks — **DONE**

**Files:**
- Created: `docs/archive/dev-sessions/2026-08-03-1341-58-driver-fault-false-positive/checks.md`
- Modified: `driver/test-park-state.sh` — the `#58` section (C1, C2, G3, G4)

**Verification — automated:**
- [x] C1 and C2 run and **fail for the expected reason** — the driver really classifies
      `driver-fault` and really writes the "no spend" claim; four attributability assertions
      rule out a broken fixture. Observed output recorded in `checks.md`.
- [x] Guards run and **pass** — G1 (`make driver-test`, 113 passed), G2 (every pre-existing
      assertion in both suites green), G3 and G4 green at freeze.
- [x] Check-reviewer dispatched read-only, given `checks.md` and the repo but not this plan and
      not the criteria's rationale. One disposition per check and per guard in
      `## Adjudication`, including the cleared ones. Two strengthenings applied before the lock.
- [x] Freeze commit `e3d3412`; sha recorded in `checks.md` by follow-up `9c09f80`.

---

## Phase 1: Require positive evidence of never-having-started, and stop claiming "no spend"

The whole change, end to end: one new helper, one tightened predicate, one honest reason. It is
a single vertical slice because C1 and C2 are two halves of one misreading and land in the same
ten lines — splitting them would produce a phase that changes a predicate while leaving the
reason next to it lying, which is not independently valuable.

**Advances:** C1, C2.

**Files:**
- Modify: `driver/agent-session-driver.sh` — add `stream_has_events`, tighten the
  `driver-fault` predicate, make the `failed` branch's reason conditional on whether the cost
  was determinable.

**Read-only this phase:** `driver/test-park-state.sh` and `driver/test-driver.sh`. The frozen
checks are the oracle; a failing frozen check is a report-back, not a fix-up.

**Key changes:**

1. A helper beside `pick_result` / `has_success_result` (around `:751`–`:771`), following their
   shape — take the stream path, answer one question, tolerate a missing file:

```bash
# The driver-fault branch below needs POSITIVE evidence that the invocation never
# reached the model, not merely the absence of an extractable cost. A stream with
# events in it is a run that started, whatever pick_result could make of it: on
# #50 a 691-event stream carrying 95 turns and $10.93 was recorded as `cost_usd: 0,
# no spend` because the result record had not been flushed when the driver read it.
# An effectively empty stream is the never-started shape. See issue #58.
stream_has_events() { # $1 = stream.jsonl path
  [ -s "$1" ] || return 1
  jq -se 'length > 0' "$1" >/dev/null 2>&1
}
```

   `-s` catches the zero-byte case first, so a stream that exists but is empty answers `no`
   without depending on `jq`'s behaviour on empty input. `jq -se 'length > 0'` then answers for
   a file with content. A stream of unparseable garbage makes `jq` exit non-zero, which reads as
   "no events" — the conservative direction: it preserves today's `driver-fault` classification
   for a case nobody has evidence about, rather than silently reclassifying it.

2. Whether the cost was determinable at all, computed next to the existing extraction at
   `:869`–`:872`. This is the distinction the ledger currently cannot draw — `cost=0` today
   means both "spent nothing" and "could not tell":

```bash
  # `cost` is 0 both when the run genuinely spent nothing and when pick_result
  # found no record to read. Only the second is an unknown, and only the second
  # may be described as one -- saying "undetermined" about a cost that WAS read
  # is this bug inverted, and G4 asserts it does not happen.
  local cost_known=0
  printf '%s' "$result" | jq -e 'has("total_cost_usd")' >/dev/null 2>&1 && cost_known=1
```

3. The classifier at `:893`–`:905`. Only the `driver-fault` arm's condition and the two reason
   strings change; the `has_success_result` arm's **condition line is untouched**, which is what
   keeps G1 green:

```bash
  elif [ "$rc" -ne 0 ] && [ -z "$session" ] && [ "${cost:-0}" = "0" ] \
       && ! stream_has_events "$raw"; then
    outcome="driver-fault"
    reason="claude exited $rc before starting (empty stream, no session, no spend) -- see $rundir/stderr.txt"
  elif [ "$rc" -ne 0 ] && ! has_success_result "$raw"; then
    outcome="failed"
    if [ "$cost_known" -eq 1 ]; then
      reason="claude exited $rc"
    else
      reason="claude exited $rc; cost undetermined (no result record in the stream) -- see $rundir/stderr.txt"
    fi
```

   The truncated-stream run now falls through to `failed`, which is the honest outcome: the run
   started, it did not finish, and the driver cannot say what it cost. `failed` is already in the
   parking list at `:1002`, so the issue still gets parked and the loop still stops — the change
   is to the *claim on the record*, not to what happens next.

**Why the `driver-fault` reason keeps "no spend":** on that branch the stream really is empty, so
the claim is now true rather than inferred, and "empty stream" states the evidence it rests on.
C2's `hasnt "no spend"` is asserted against the truncated-stream fixture's reason only.

**Verification — automated:**
- [x] C1 and C2 pass: `make park-test` — the `#58 C1/C2` block reads
      `ok C1: the run is NOT classified driver-fault`,
      `ok C2: the recorded reason names the cost as undetermined`,
      `ok C2:   and does not claim the run did not spend`. **48 passed, 0 failed.**
- [x] G3 passes (`ok G3: the never-started run is still classified driver-fault`) and G4 passes
      (`ok G4: a run whose cost IS determinable is not reported as undetermined`).
- [x] G1 passes: `make driver-test` — 113 passed, 0 failed.
- [x] G2: no case lost, newly skipped or newly failing. park-test went 45→48 passed and 3→0
      failed; the 3 gained passes are exactly C1 and C2's previously-failing assertions.
- [x] `make check` passes — `all checks passed`.
- [x] Tamper diff empty: `git diff e3d3412 -- driver/test-park-state.sh` produced no output.
      `--stat` since the freeze shows only `agent-session-driver.sh` and `checks.md`'s
      sanctioned `Frozen at` line — no collateral edits.

**Verification — manual:**
- [ ] None. Both criteria are machine-checkable, which is why this is `auto-ok`.

---

## Out of scope, noted for a future session

- **Closing the race** (the issue's suggested item 2 — wait for the child to fully exit before
  reading its stream). The spec's Design decisions record this as deliberately separate: it would
  make this instance rarer without making the inference sound.
- **`cost_usd` as `null`/`unknown`** (item 3). The spec's "What we're NOT doing" rules it out —
  `runs.jsonl` has readers and a type change is a wider blast radius than this issue's evidence
  supports.
- **`--classify-only`'s extraction at `:1087`–`:1089`** reads cost and session the same way, and
  its `say` line prints an empty cost the same way. It is NOT the same defect — that path forces
  `rc=0` and takes its outcome from the PR, so it has no `driver-fault` branch and makes no
  "no spend" claim. Checked rather than assumed, because #5's C2 exists precisely because a
  duplicated case list was fixed at one site and not the other. Left alone.
