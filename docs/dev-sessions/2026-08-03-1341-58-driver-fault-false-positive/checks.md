# Frozen acceptance checks

**Source:** https://github.com/lmorchard/agent-sessions/issues/58
**Frozen at:** `e3d3412` (2026-08-03)
**Check files — read-only from Phase 1 onward:**
- `driver/test-park-state.sh`

`driver/test-driver.sh` is NOT in that list even though G1 lives there: G1 asserts an *existing*
line keeps passing, and nothing in this work should edit that file. A diff against it is a
finding, not a sanctioned edit.

## C1

CRITERION: GIVEN a run whose `stream.jsonl` contains events but no parseable `result` record,
WHEN the driver classifies a nonzero exit, THEN it SHALL NOT classify the run `driver-fault`.

CHECK: a new case in `driver/test-park-state.sh` — a `claude` stub that emits assistant events
and then exits nonzero **without** a `result` record; assert the recorded outcome is not
`driver-fault`. Run by `make park-test`.

AT FREEZE: **fails**, for the criterion's own reason —

```
FAIL  C1: the run is NOT classified driver-fault
   expected: does NOT contain: driver-fault
   actual:   driver-fault
```

Attributable: the four assertions preceding it pass at freeze, establishing that the stub really
ran, the run really wrote a ledger row, the captured stream carries exactly 2 events, and it
carries 0 result records. So the failure is the driver's classification, not a broken fixture.

## C2

CRITERION: WHEN the cost of a run cannot be determined, THEN the recorded reason SHALL say so,
and SHALL NOT assert that the run did not spend.

CHECK: the same fixture — assert the reason does not contain the "no spend" claim and does name
the cost as undetermined. The needle is `cost undetermined`, named once in the suite as
`COST_UNKNOWN_NEEDLE` and verified absent from the driver source and from every reason it can
currently write.

AT FREEZE: **fails**, both halves —

```
FAIL  C2: the recorded reason names the cost as undetermined
   expected: contains: cost undetermined
   actual:   claude exited 3 before starting (no session, no spend) -- see .../stderr.txt
FAIL  C2:   and does not claim the run did not spend
   expected: does NOT contain: no spend
   actual:   claude exited 3 before starting (no session, no spend) -- see .../stderr.txt
```

## Guards

(Pass today; must keep passing. Not criteria — they can't fail at freeze.)

- **G1:** The classifier still consults `has_success_result`. CHECK: `driver/test-driver.sh:353`
  counts non-comment hits on `rc" -ne 0 ] && ! has_success_result`. Run by `make driver-test`.
  AT FREEZE: **passes** (113 passed, 0 failed).
- **G2:** Normal classification is unchanged: exit 0 reads the gate; nonzero-with-a-success-result
  still reads the gate rather than reporting `failed` (the #656 case). CHECK: `make driver-test`
  and `make park-test`, no case lost, newly skipped or newly failing.
  AT FREEZE: **passes** — every pre-existing assertion in both suites is green.
- **G3:** A genuine never-started run — empty stream, no session, no cost — is **still**
  `driver-fault`. CHECK: a fixture with a zero-byte stream asserts the classification survives.
  This is the guard that stops C1 being satisfied by deleting the branch.
  AT FREEZE: **passes**, with two attributability assertions (the stream is zero bytes AND the
  stub really ran, so the zero bytes are its output rather than its absence).
- **G4:** *Added at freeze, from C2's adjudication — see below.* A run whose cost IS determinable
  is not reported as undetermined. CHECK: a fixture whose stub emits an
  `error_during_execution` result carrying `total_cost_usd: 10.93` and exits nonzero; assert the
  reason does NOT contain `cost undetermined`, and that the ledger's `.cost_usd` really is
  `10.93` (the non-vacuity proof that the cost was extractable).
  AT FREEZE: **passes**.

## Adjudication

Check-reviewer: a fresh-context, read-only dispatch (no Edit/Write), given this manifest and the
repo but neither an implementation plan (none existed) nor the criteria's rationale. One
disposition per check and per guard, including the ones it cleared.

- **C1: strengthened.** The reviewer cleared six attacks (delete the branch, reorder the `elif`
  chain, rename the outcome in either direction, key on cost-emptiness rather than cost-zero,
  suppress the ledger row, route to the gate branch) — each blocked by G3 or by an
  attributability assertion. The hole it found: the fixture's `claude` stub emitted a
  `{"type":"system","subtype":"init","session_id":...}` line, giving the fixture **two** signals
  distinguishing it from G3's — the stream has events (the criterion's GIVEN) *and* a session id
  exists somewhere in the stream (not the criterion). A fix that scanned the whole stream for any
  `session_id` would green C1, keep G3 green, and leave a genuine instance of C1's GIVEN broken:
  a stream with events but no `init` record would still classify `driver-fault`.
  **Closed by** removing the `system/init` line, and pinning the event count at exactly 2 with a
  `check` rather than a `>= 1` threshold — so the fixture's shape is enforced by the suite instead
  of by a comment. Freeze verdict undisturbed: `pick_result` matches `.type=="result"` only, so
  the driver was blind to that line either way.

- **C2: strengthened.** Cleared: rewording only the driver-fault reason (C1 stays red), dropping
  the `no spend` phrase without adding the needle (the paired positive assertion stays red), and
  emitting the needle from an unreached branch. The hole: **the positive needle had no negative
  control anywhere in either suite.** Appending `cost undetermined` unconditionally to the
  `failed` branch's reason would green both C2 assertions without the driver ever asking whether
  the cost was determinable — and would manufacture #58 inverted, stamping "cost undetermined"
  onto the ledger row of a run whose cost was extracted perfectly well. A false fact about a run,
  which is the class this issue exists to close.
  **Closed by** adding **G4** above.

- **G1: accepted.** The reviewer notes it is a literal-text guard: it constrains the classifier's
  *spelling*, not its behaviour, and would break on a legitimate reorder of the conjuncts or pass
  if `has_success_result` were called and its result discarded. Accepted unchanged anyway — it is
  a pre-existing assertion in a neighbouring suite, rewriting it here would be editing an oracle
  this issue did not author, and the intended change (tightening the *driver-fault* condition,
  leaving the `failed` branch alone) leaves it untouched. Recorded so a break in it reads as a
  signal rather than a surprise.

- **G2: accepted.** The reviewer confirmed the new section is append-only after every pre-existing
  case, that its two new helpers shadow no existing name, and that its state/stub/skill/repo dirs
  and argv logs are disjoint from every other case's — so no ordering dependence and no way for a
  new case to mask an old one. All pre-existing assertions green.

- **G3: accepted.** Attacked by starving its inputs (a missing run dir renders `missing`, a
  missing ledger row renders the no-row sentinel — both fail closed, neither passes vacuously),
  and by every C1 shortcut above, all of which break it. Its `claude_calls >= 1` assertion is the
  right control for "zero bytes because the stub ran and said nothing" versus "zero bytes because
  the stub never ran".

- **G4: accepted** — authored during this adjudication in response to C2, and passing at freeze,
  which is what makes it a guard rather than a criterion.

### Residual hole, accepted knowingly

C2's negative half (`hasnt "no spend"`) is substring-exact, so a reword to e.g. "no *recorded*
spend" would slip past that one assertion. Left as the criterion's CHECK literally specifies
rather than widened unilaterally — widening what a frozen criterion asserts is an amendment, and
this is not worth one. The weight is carried by C2's positive needle plus G4, which together
require the phrase to appear when the cost is unknown and to be absent when it is known.

## Amendments

(none)
