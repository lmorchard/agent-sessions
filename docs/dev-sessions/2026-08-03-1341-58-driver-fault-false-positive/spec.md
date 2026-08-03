# A killed run can log cost_usd: 0 for a run that spent $10.93

**Source:** https://github.com/lmorchard/agent-sessions/issues/58

A run that is interrupted can record **`cost_usd: 0` and `"no session, no spend"` for a run that spent
real money**, because the driver classifies before the child has flushed its `result` event.

## Observed

Issue #50, run `50-20260801T161622Z`, 2026-08-01. The run was interrupted at ~33 minutes, after it had
pushed five commits and opened PR #56. The driver recorded:

```json
{"issue":50,"exit":143,"cost_usd":0,"session_id":"","outcome":"driver-fault",
 "reason":"claude exited 143 before starting (no session, no spend) -- see .../stderr.txt"}
```

Every one of those fields is wrong. The same run's `stream.jsonl` contains a `result` event carrying:

```
subtype: 'error_during_execution'   is_error: True
total_cost_usd: 10.929119500000004
session_id: '12420e62-62e6-4341-85c6-68d9a4751753'
num_turns: 95
```

**$10.93 spent, logged as $0. 95 turns, logged as "before starting".**

`--classify-only 50` afterwards recovered it correctly — *"recovered from stream: cost
$10.929119500000004 session 12420e62-…"* — which is both the mitigation and the proof the data was
always there.

## It is a race, and the second run proves it

The very next attempt, `50-20260801T171059Z`, was interrupted the same way with the same exit code 143
— and recorded `cost_usd: 12.924967999999993` with a real session id. Same code path, same signal,
opposite result. So this is not a parsing bug in `pick_result`; it is **timing**. When the driver
reaches classification before the terminated child has flushed its final `result` record,
`pick_result` matches nothing, and `cost` and `session` come back empty.

The driver's own log line for the first run shows the empty value directly: `exit 143 cost $ session
none` — an empty string, not a zero.

## Why the empty value becomes a false positive

`driver/agent-session-driver.sh`:

```bash
elif [ "$rc" -ne 0 ] && [ -z "$session" ] && [ "${cost:-0}" = "0" ]; then
  outcome="driver-fault"
  reason="claude exited $rc before starting (no session, no spend) -- see $rundir/stderr.txt"
```

The predicate is sound on its own terms — no session and no spend really would mean the invocation
never reached the model. What is wrong is treating **"the extractor found nothing"** as **"there is
nothing"**. That is `findings.md` defect class 2, *a null must never render as a positive*, landing in
the cost ledger.

The comment above that branch explains it was added so a driver bug would not be mistaken for a run
failure — a good reason. The branch simply has no way to tell "never started" from "started, and I
read the stream too early".

## Why this one is worse than the failure it sits next to

`inflight.json` exists because *"a driver that dies between invoking and classifying leaves no
record"* — real money spent, invisible. This is the same family and strictly worse: **it leaves a
record, and the record is confidently wrong.** A missing row prompts someone to go looking. A row
saying `cost_usd: 0, no spend` does not.

It also corrupts the input to any future cost accounting — see #52, which is about the recorded cost
band being stale. Two of this repo's five runs on 2026-08-01 were interrupted, and one of them
contributed a $0 row to the ledger for an $10.93 run.

## Suggested shape (not a decision — needs intake)

1. **Make the `driver-fault` predicate require positive evidence of never-having-started**, rather
   than inferring it from two empty variables. A stream with 691 events and 95 turns is not a run that
   never reached the model; an effectively empty `stream.jsonl` is. The discriminating check is a
   fixture where the stream is non-empty but `pick_result` returns nothing — today that classifies
   `driver-fault`, and it should not.
2. **Close the race itself** by waiting for the child to fully exit before reading its stream, so the
   flush is complete by construction rather than by luck.
3. Consider whether **a `cost_usd` of 0 alongside a non-empty stream should be refused outright** —
   written as `null`/`unknown` rather than `0`. Zero is a claim; unknown is the truth, and the ledger
   currently cannot express it.

Note items 1 and 2 are independent, and 2 alone would leave the false inference in place for any other
cause of an unreadable stream.

**Triaged 2026-08-01** — the marker now leads this body and the criteria are below.

---

## Verifiable acceptance criteria

- **C1.** GIVEN a run whose `stream.jsonl` contains events but no parseable `result` record, WHEN the
  driver classifies a nonzero exit, THEN it SHALL NOT classify the run `driver-fault`.
  **CHECK:** a new case in `driver/test-park-state.sh` — a `claude` stub that emits assistant events
  and then exits nonzero **without** a `result` record; assert the recorded outcome is not
  `driver-fault`.
  **DEMONSTRATED FAILING:** observed live on run `50-20260801T161622Z` — recorded
  `driver-fault / cost_usd 0 / "no session, no spend"` for a run whose stream carried
  `total_cost_usd: 10.929…`, a real `session_id` and `num_turns: 95`.
  **ORACLE EXISTS NOW:** `make_stubs` and `run_driver` in `driver/test-park-state.sh` already build a
  `claude` stub (`:139` emits a `result` record today) and the suite already asserts on `runs.jsonl`
  rows. The new case varies the stub; it builds no new harness.

- **C2.** WHEN the cost of a run cannot be determined, THEN the recorded reason SHALL say so, and
  SHALL NOT assert that the run did not spend.
  **CHECK:** the same fixture — assert the reason does not contain the "no spend" claim and does name
  the cost as undetermined.
  **DEMONSTRATED FAILING:** the live row above asserts `no session, no spend` about $10.93.

## Regression guards

- **G1.** The classifier still consults `has_success_result`. **CHECK:** `driver/test-driver.sh:353`
  already asserts this by counting non-comment hits on `rc" -ne 0 ] && ! has_success_result` — it must
  keep passing. Named explicitly because that line is the nearest existing assertion to the branch
  being changed, and because the `#51`/`#27` collision happened by *not* checking the neighbouring
  suite before writing a criterion.
- **G2.** Normal classification is unchanged: exit 0 reads the gate; nonzero-with-a-success-result
  still reads the gate rather than reporting `failed` (the #656 case). **CHECK:** `make driver-test`
  and `make park-test`, no case lost, newly skipped or newly failing. Passes today.
- **G3.** A genuine never-started run — empty stream, no session, no cost — is **still**
  `driver-fault`. **CHECK:** a fixture with a zero-byte stream asserts the classification survives.
  **This is the guard that stops C1 being satisfied by deleting the branch**, which is the cheap fix
  and would lose the distinction the branch was added for.

## Tier: auto-ok

**Trigger 1 does not fire.** Both criteria are assertions over a `runs.jsonl` row produced by an
existing stub harness, and C1's failure was observed in production rather than hypothesised.

**Trigger 2 does not fire, mechanically.** `driver/agent-session-driver.sh` is on `CLAUDE.md`'s
drivable allowlist; only `driver/gate.py` is carved out, and this work does not touch it.

**But read this before driving it, because the mechanical answer is doing real work here.** This issue
edits the branch that decides **a run's own outcome** — closer to the oracle than
[#39](https://github.com/lmorchard/agent-sessions/issues/39), which edited a park *reason*. `CLAUDE.md`
names this exposure and declines to gate it (*"Path granularity cannot express 'this file except its
classification path'"*), ending with **"Revisit if a run ever touches that routing."** #39 was the
first firing of that clause; this is the second, and the stronger one, because a run implementing it
is editing the code that will classify **its own** failure. The mitigations `CLAUDE.md` relies on all
apply — the fixture suite, `make check`, a human at the merge gate — and G3 specifically blocks the
self-serving version of the change. **Whether that clause should now become a gate is a decision for
Les, not something to resolve by analogy.**

## Design decisions

- **Decision:** fix the false inference, and treat closing the race as separate.
  - **Why:** the two are independent. The race explains *why* the extractor came back empty on one run
    and not the next; the false inference is what turns an empty extraction into a confident
    `no spend`. Waiting for the child to exit would make this instance rarer without making the
    inference sound — any other cause of an unreadable stream reproduces it.
  - **Rejected:** only closing the race.

## What we're NOT doing

- **Changing `cost_usd`'s type to null.** It would express the truth better, but `runs.jsonl` has
  readers (`park_reason`, `run_progress.py`) and a type change is a wider blast radius than this
  issue's evidence supports. C2 puts the honesty in the reason instead.
- **Touching `driver/gate.py`.** Off-limits, and unrelated: it classifies PR bodies, not run exits.
- **Retro-fixing historical rows.** `--classify-only` already recovers them on demand, and it did.
