# Session notes — #5, park state as a GitHub label

**Date:** 2026-07-29 · **Branch:** `fix/5-park-label` · **Tier:** `auto-ok` · **Freeze:** `4c46753`
**Route:** hand-run through `plan.md` → `execute.md` → `pr.md`, not driven. Les's call, and the
reason stands: D2 reinstated a criterion and revised a recorded decision, so the criteria needed
rework before the freeze, and an unattended run interpreting a body rewritten minutes earlier is the
wrong first use of `run-self`.

## What changed

Park state moved from `./.driver-state/parked.jsonl` to a `driver-parked` label on the issue.
`parked_numbers()` now reads the issues JSON that `select_issues` already fetched; `apply_park_state()`
replaces the parking case list that was duplicated across the normal and `--classify-only` paths, and
adds the un-park a gate verdict implies. `runs.jsonl` keeps supplying the skip reason.

**Selection now consults no local state at all.** That is the durable result — marker, tier, open
PRs, board column and park bit all come from GitHub, so the answer is the same on any machine.

## The decision changed mid-session — D1 → D2

The handoff said D1 (derive the park list from `runs.jsonl`) was settled and not to re-litigate it,
and I didn't. What reopened it was Les asking where the durable store should live: D1 answered
*correctness* but left the store local, so **C3 had no named mechanism**, and `plan.md`'s "a missing
load-bearing decision is a stop, not a guess" applied. Les leaned GitHub; working it through, that
was right for reasons beyond avoiding laptop lock-in — repo scoping by construction, no state for a
GHA runner to carry or commit back, and park state visible where a human decides to `--retry`.

D2 revises D1 in part rather than replacing it: the read side still abandons `parked.jsonl`, and
`runs.jsonl` still carries the reason. **The ledger is history, the label is current state** — and
conflating those two was the bug. Recorded in the issue body (comments are invisible to downstream
modes) and, after `main` moved the roadmap onto the board mid-session, summarised under
`docs/design.md`'s **Resolved decisions** instead — decision provenance, not state.

Cost, paid knowingly: C2 came back, and the driver became a GitHub writer. `CLAUDE.md` now bounds
that — issue metadata, never issue or PR content — which was Les's third option on the tier question.

## What the freeze caught, and what mutation testing caught after

**Three fixture defects, found before the freeze commit**, all by the harness-sanity section that
exists to make failures attributable. Two were this project's dominant defect class — a row satisfied
by evidence *adjacent* to what it names — inside the check file meant to catch it:

1. C1 died on `PARKED_LOG: unbound variable`: a bash error, not an empty park list.
2. C4's skip assertion **passed for the wrong reason** — the shared fixture served an open PR for #7,
   so `SKIP #7 already has an open PR` satisfied a row about the *label*.
3. `and says why` matched the fixture's issue **title** (`parked issue`), not a skip reason.

**Then mutation testing found a hole the frozen checks could not see.** Six mutations; five flipped
them, one did not:

| Mutation | Frozen checks |
|---|---|
| delete the label write on park | 6 fail |
| delete the un-park write | 4 fail |
| rename the label | 6 fail |
| drop the `--classify-only` call site | 7 fail |
| rename `parked_numbers` | 3 fail (fails closed, as designed) |
| **stop requesting `labels` in the issue query** | **all 27 still pass** |

The stub served a fixed payload regardless of the `--json` field list, so removing the field the
filter depends on was invisible — while in production the park list would have gone permanently
empty. **A stub that ignores the requested field list cannot see a missing field.**

Handled by adding coverage *beside* the oracle rather than editing it: a new assertion in the
editable `test-driver.sh` whose stub honors the requested fields, verified to fail under the same
mutation. **Not an amendment** — the frozen checks are incomplete here, not wrong, so no verdict
changed at either tree and nothing was owed a downgrade.

## The verifier caught the author, twice

Both dispatches were read-only `Explore` (no `Edit`/`Write`, so structurally unable to touch the
oracle they grade), per the carve-out in `design.md`'s Resolved decisions. Les adjudicated the
dispatch explicitly first, because this session's operator instruction and that carve-out point
opposite ways.

**First run** found the real defect: C2's three needles — `--add-label`, the label name, and
`issue edit 7` — matched *independently* over the whole concatenated argv log, and the label name
also appears in the logged `gh label create` line. So `gh issue edit 7 --add-label wrong-label` plus
`gh label create driver-parked` would have passed all three. Adjacent evidence, inside the check
written to prevent it. Tightened as a **clarification** — classified by running the both-trees test,
not by asserting it — and proven load-bearing: with the driver mutated to apply the wrong label, the
tightened wording fails where the original passed 27 of 27.

**Second run** audited the clarification itself and found two descriptive gaps in the log entry plus
**residual prefix-looseness** in the tightened predicate (`issue edit 70` satisfies `issue edit 7`).
Recorded in `checks.md` rather than closed, with the reasoning; the first case is the one with a
non-adversarial failure mode and is where to start if it's revisited.

Five for five now on the verifier catching its author across this project's history.

## Evidence

- Frozen checks: **27/27**, from 14/27 at freeze. `make check`: **62 bash assertions + pytest, green.**
- Tamper: `git diff 4c46753 -- driver/test-park-state.sh` **empty**.
- G7: `git diff origin/main..HEAD --stat -- skills/ driver/gate.py` **empty** — neither the skill nor
  the oracle was touched.
- **Live, stub-free:** created the real label, applied it to #6, and `make dry-run-self` reported
  `SKIP    #6  parked: carries the driver-parked label; no local run record on this host` — the
  fallback path firing correctly, since #6 has no ledger row. Removing it restored `ELIGIBLE #6`.
  Repo left as found: label deleted, #6 back to `auto-ok` alone.
- Two `gh` facts probed rather than assumed, now in `findings.md`: `--remove-label` on an absent
  label exits **0**; `gh label create` on an existing label exits **1**.

## Deviation, named not hidden

**The check-author subagent was not dispatched; the frozen checks were authored inline.** A
check-author needs `Write`, and the operator's standing grant covers read-only `Explore` only
(`design.md`, Resolved decisions, 2026-07-28). Same deviation as moves 4b/5/7. What partly
substitutes: the criteria were authored at triage and in D2 *before* any implementation approach
existed, and the freeze commit predates every implementation line.

## The review cycle — and the same defect a third time

Copilot left four comments; three fixed, one disputed and its thread left open.

**The one that mattered caught the adjacent-evidence class again, in the fix I had just written for
it.** My new slice test in the editable suite asserted `SKIP    #7` — which *any* skip satisfies, so
a broken marker or tier parse would have skipped #7 and left the test green through the exact
regression it exists to catch. I had tightened the frozen file's C4 needle for precisely this reason
an hour earlier and missed it one file over. Now `SKIP    #7  parked`, verified both ways: the
labels-dropped mutation fails it, and so does #7 skipping for a *tier* defect, where the old needle
passed.

Three instances in one session, all mine, all in checks written to catch it — after reading the
findings entry that names it as the dominant class. **Consistent with the note that knowing a hazard
does not prevent it**; what caught all three was running the check and reading *which line* satisfied
it, not more care.

Also fixed: `parked.jsonl` records now carry `repo` (its absence is something this PR's own rationale
cites against the file, so omitting it while quoting that argument was incoherent), and `check`'s
help text no longer enumerates a target list that had gone stale.

**Disputed and left open:** creating the label once per invocation rather than per park event. Bounded
by `--max-issues` (1, or 2 in `make loop`), so it is two extra API calls against a 5000/hour limit in
exchange for an invocation-scoped flag and a first-park special case. Fair about a design that would
not scale; not worth it at this volume. **That open thread is the only row holding the gate at
`human-merge-required`** — resolving a thread I merely disagreed with would make "no unresolved
threads" self-satisfiable, which is the one thing that row cannot survive.

## Left undone, deliberately

- **The four stale `parked.jsonl` entries** were not pruned and did not need to be — no issue carried
  the label, so the park list started empty. Trigger 2 never fired, which is what kept this `auto-ok`.
- **No live park→un-park round trip through a real run.** The write side is proven against stubs and
  the read side live; a real park would mean spending a real run to fail on purpose.
- `#5`'s own selection still shows `ELIGIBLE` in `dry-run-self` because it has no open PR yet. It
  will skip on the PR once opened, which is the pre-existing behaviour.
