# Frozen acceptance checks

**Source:** https://github.com/lmorchard/agent-sessions/issues/51
**Frozen at:** `fa4ca83` (2026-08-01)
**Check files — read-only from Phase 1 onward:**
- `driver/test-park-state.sh`

Criteria and checks are copied verbatim from the issue spec. The one implementation file the
work may touch is `driver/agent-session-driver.sh`; it is not a check file, so the check files
and the implementation files are disjoint and the ordinary tamper diff applies.

## C1

CRITERION: GIVEN a state dir whose `inflight.json` names a **live** child pid, WHEN the driver is
invoked with `--dry-run`, THEN it SHALL still print the orphan warning, complete selection, and
exit 0.

CHECK: a new case in `driver/test-park-state.sh` — a fixture state dir holding `inflight.json`
and `runs/<n>/child.pid` with a live pid; assert exit status 0, the orphan warning present in the
output, and at least one selection line printed. Run by `make park-test`.

Concretely, three assertions under the heading `#51 C1: --dry-run reports a live orphan but does
not refuse`:

- `dry-run exits 0 with a live orphan present` — exit status is `0`
- `  and still prints the orphan warning` — output contains `ORPHAN STILL RUNNING`
- `  and still completes selection` — output contains `ELIGIBLE #8`

plus an attributability control, which must PASS at freeze:

- `  control: with the pid file removed, dry-run exits 0` — same fixture, same flags, `child.pid`
  deleted; exit status is `0`

AT FREEZE: **C1 fails**, observed 2026-08-01 by running `make park-test`:

```
#51 C1: --dry-run reports a live orphan but does not refuse
  FAIL  dry-run exits 0 with a live orphan present
     expected: 0
     actual:   2
  ok      and still prints the orphan warning
  FAIL    and still completes selection
     expected: contains: ELIGIBLE #8
     actual:   ...|WARNING: a previous run died before recording its outcome:|  issue #99 ...
  ok      control: with the pid file removed, dry-run exits 0
```

Correct reason: `2` is `die`'s exit status, reached on the line immediately after the
`ORPHAN STILL RUNNING` message that assertion 2 confirms was printed. The truncated actual for
assertion 3 shows the last thing printed was the inflight warning — selection was never reached.
Not a bash error, an unbound variable, a missing fixture or a stub typo.

**Two of C1's three assertions fail, not three — stated plainly rather than smoothed over.**
`  and still prints the orphan warning` passes today, because today's driver prints the warning
and *then* dies; only the non-refusal is absent. It was not contrived into failing: doing so would
have meant folding the exit status into it and destroying its independent value. Its job is to be
a guard *inside* C1 — it fails if the implementer buys the exit-0 by short-circuiting the warning
block for `--dry-run`, which is the most likely wrong fix. C1 as a criterion is the conjunction,
and the conjunction discriminates.

**Satisfiability of assertion 3, verified empirically before the freeze was committed** — a frozen
check that can never go green is worse than no check. With the same fixture and the pid file
removed, the driver emits:

```
== select ==
repo stub/repo: read 2 open issues
  SKIP    #7  parked: carries the driver-parked label; no local run record on this host
  ELIGIBLE #8  tier: auto-ok
eligible: 1
```

So `ELIGIBLE #8` is a string the driver really produces under the stock `make_stubs` fixture; the
refusal is the only thing standing between assertion 3 and green.

## Guards

(Pass today; must keep passing. Not criteria — they can't fail at freeze.)

- **G1.** A real `run` against the same live-orphan fixture still exits non-zero **and never
  invokes `claude`**. CHECK: a park-test case asserting the argv log records zero `claude`
  invocations. This is the guard that stops the fix being a deletion — the cheapest way to green
  C1 is to remove the refusal, which would also silently re-open the two-concurrent-runs hazard
  the refusal exists for.

  Assertions: `a real run still refuses while the orphan is live` (non-zero exit) and
  `  and never invokes claude` (zero `^claude ` lines in the argv log).

  **Non-vacuity:** the zero-count assertion is only meaningful because the claude stub logs every
  invocation and an existing control in this same file proves it does — `#39 C1`'s
  `control: with a healthy query the same run DOES invoke claude`. If the stub ever stops
  logging, that control fails and this guard is exposed as vacuous. No second control is added,
  deliberately: a duplicate would drift from the original.

- **G2.** `--classify-only` behaviour is unchanged: it still refuses while the orphan is live.

  Assertion: `--classify-only still refuses while the orphan is live` (non-zero exit).

- **G3.** The existing park cases pass unchanged — no case lost, newly skipped or renamed.
  CHECK: `make park-test`.

  Made mechanical: every assertion label present at freeze-baseline must still appear as an `ok`
  line afterwards. The baseline inventory was captured from the pristine tree at
  `050c458` and is stored beside this file as `g3-baseline-labels.txt`. The invariant is
  "none lost", not the count.

  Verification command:
  `make park-test 2>&1 | grep -E '^  ok '` — every line of `g3-baseline-labels.txt` must appear.

## Guards at freeze

All three PASS at freeze, as they must — a guard that already fails is a pre-existing break, not
a guard. Observed 2026-08-01 in the same `make park-test` run:

```
#51 G1/G2: run and --classify-only still refuse, and spend nothing
  ok    a real run still refuses while the orphan is live
  ok      and never invokes claude
  ok    --classify-only still refuses while the orphan is live
```

G3 at freeze: all 28 labels in `g3-baseline-labels.txt` printed as `ok`; tally
`33 passed, 2 failed`, the two failures being C1's.

## Amendments

(Append-only. Empty unless an amendment was made.)

_None._

## Tamper verdict

(Recorded by the independent verifier.)
