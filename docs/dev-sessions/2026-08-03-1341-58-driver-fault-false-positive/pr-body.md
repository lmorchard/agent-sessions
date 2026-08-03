## Summary

- The `driver-fault` branch inferred *"the invocation never reached the model"* from two empty
  variables — no session id, no cost. Both come from `pick_result`, which emits nothing when the
  stream carries no `result` record, so **"the extractor found nothing" was recorded as "there is
  nothing."**
- On run `50-20260801T161622Z` that put `cost_usd: 0` and `"no session, no spend"` on the ledger
  row of a run that spent **$10.93** across 95 turns and had already opened a PR. This is worse
  than the missing-row failure `inflight.json` exists to bound: a missing row sends someone
  looking, a confident zero does not.

## Design Decisions

**Fix the false inference; treat closing the race as separate work.** The race explains *why* the
extractor came back empty on one run and not the next; the false inference is what turns an empty
extraction into a confident `no spend`. Waiting for the child to exit would make this instance
rarer without making the inference sound — any other cause of an unreadable stream reproduces it.
Rejected: closing only the race.

`cost_usd`'s type is deliberately unchanged. `null` would express the truth better, but
`runs.jsonl` has readers (`park_reason`, `run_progress.py`) and a type change is a wider blast
radius than this issue's evidence supports. The honesty goes in the reason instead.

## Changes

All in `driver/agent-session-driver.sh`'s classifier:

- **`stream_has_events`** — the positive evidence. An empty stream is the never-started shape; a
  stream with events in it is a run that started, whatever `pick_result` could make of it.
  Unparseable input reads as "no events", which *preserves* today's classification rather than
  silently reclassifying a case nobody has evidence about.
- **`cost_known`** — distinguishes a cost read as `0` from a cost that could not be read at all.
  The ledger's `cost_usd` cannot express the difference, so the reason must.
- **The truncated-stream run now falls through to `failed`**, with the cost named as undetermined
  instead of `driver-fault` asserting it never spent. It is still parked and still stops the loop
  — what changes is the claim on the record, not what happens next.

The `has_success_result` arm's condition line is untouched, which is what keeps G1 green.

**`--classify-only` was checked and deliberately left alone:** it forces `rc=0` and takes its
outcome from the PR, so it has no `driver-fault` branch and makes no "no spend" claim. Checked
rather than assumed, because #5's C2 exists precisely because a duplicated case list was fixed at
one site and not the other.

## Acceptance criteria

| id | criterion | check | result |
|---|---|---|---|
| C1 | a stream with events but no `result` record is not classified `driver-fault` | `make park-test` → `ok C1: the run is NOT classified driver-fault` | pass |
| C2 | an undetermined cost is reported as undetermined, and not as "no spend" | `make park-test` → `ok C2: the recorded reason names the cost as undetermined` · `ok C2: and does not claim the run did not spend` | pass |
| G1 | the classifier still consults `has_success_result` | `make driver-test` → `ok the failed branch consults the stream before overruling the gate` | pass |
| G2 | normal classification unchanged; no case lost, skipped or newly failing | `make driver-test` (113 passed, 0 failed) · `make park-test` (48 passed, 0 failed) | pass |
| G3 | a genuine never-started run is **still** `driver-fault` | `make park-test` → `ok G3: the never-started run is still classified driver-fault` | pass |
| G4 | a determinable cost is not reported as undetermined | `make park-test` → `ok G4: a run whose cost IS determinable is not reported as undetermined` | pass |

Verified by an independent verifier (fresh context, `checks.md` and the repo only — not the plan,
not the notes). Frozen at `1fdce99`; tamper diff clean and re-runnable, since the freeze commit is
an ancestor of this head.

**G3 and G4 are the load-bearing guards.** G3 blocks the cheap fix — deleting the branch, which
would green C1 and throw away the distinction the branch exists for. G4 blocks the cheap fix for
C2 — emitting `cost undetermined` unconditionally, which would green C2 while stamping the phrase
onto runs whose cost was read perfectly well, i.e. this defect inverted.

## Review notes — two holes the freeze caught before the lock

Recorded because both would have produced a green run that did not do the work:

1. **C1's fixture leaked a second signal.** Its stub emitted a `system/init` record carrying a
   `session_id`, so a fix that scanned the whole stream for any `session_id` would have greened
   C1, kept G3 green, and left the criterion's actual case broken. Closed by removing the line and
   pinning the event count at exactly 2 with an equality check.
2. **C2's needle had no negative control.** Closed by adding G4.

Both were found by a read-only check-reviewer dispatched before any implementation existed.
Strengthening at that point costs no tier — nothing was frozen yet — which is the whole reason
that step sits before the freeze commit rather than after it.

## Known limits

- A malformed (unparseable) non-empty stream still classifies `driver-fault`. Deliberate and
  commented: it preserves current behaviour for a case with no evidence behind it.
- `cost_known` is consulted only in the nonzero-exit / no-success-result branch — the path C2's
  check exercises. A timeout (rc 124) records no such note.

## Merge gate

<!-- agent-session:gate -->
```yaml
tier: auto-ok
checks: C1 pass · C2 pass
guards: G1 pass · G2 pass · G3 pass · G4 pass
tamper: clean
freeze: 1fdce99
project-gates: make check green
ci: pending
threads: pending
risk-paths: none
amendments: none
verdict: pending
reason: opened with pending per pr.md step 6 -- CI, threads and the post-review verifier report do not exist yet
```

## References

- Spec: `docs/dev-sessions/2026-08-03-1341-58-driver-fault-false-positive/spec.md`
- Checks: `docs/dev-sessions/2026-08-03-1341-58-driver-fault-false-positive/checks.md`
- Plan: `docs/dev-sessions/2026-08-03-1341-58-driver-fault-false-positive/plan.md`
- Notes: `docs/dev-sessions/2026-08-03-1341-58-driver-fault-false-positive/notes.md`
- Closes #58

---

### ⚠️ For Les — a governance decision this PR raises, not one it makes

`CLAUDE.md`'s risk-gated section names the exposure that `agent-session-driver.sh` contains the
outcome *routing*, declines to gate it (*"Path granularity cannot express 'this file except its
classification path'"*), and ends **"Revisit if a run ever touches that routing."**

**This run touched that routing** — an unattended run editing the branch that classifies
unattended runs, including its own. The tier stayed `auto-ok` because trigger 2 does not fire
mechanically (`driver/gate.py` is the only carve-out and is untouched), and the mitigations
`CLAUDE.md` relies on all held: G3 caught the cheap fix, the check-reviewer caught two ways to
fake the expensive one, `make check` is green, and there is a human at this gate.

This is the **second** firing of that revisit clause and the stronger one (#39 was the first, and
edited only a park *reason*). Whether the clause should now become a gate is your call — this run
deliberately did not touch `CLAUDE.md`, since resolving it by analogy is exactly what the clause
was written to prevent.
