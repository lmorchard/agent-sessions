
`parked.jsonl` is append-only with **no un-park record**, so a recovered run leaves a park entry
that is now false. Verified live: the file carries stale `parked` entries for **#585 (twice),
#710, and #656** — and all four later reached `gate-eligible` in `runs.jsonl`.

Moot in practice today: #585 and #710 are closed, and #656 has an open PR so selection skips it
anyway. But the state file is wrong about four issues, and selection consults it
(`parked_numbers()`), so any future change that trusts the park list inherits the lie.

Note this is broader than previously recorded — earlier notes named only #656.

Couples to the durable-park issue: whatever fixes portability should probably fix correctness in
the same pass, since both are about the park list being a poor record of state.


---

## Scope widened at triage (2026-07-27): this issue now owns `parked.jsonl` entirely

Absorbed the **durable park mechanism** from **#3**, which is now the GHA host only. Correctness
(this issue's original subject) and durability (per-machine storage) touch the same file and turn
on the same undecided question — *what is a park record, and where does it live?* Two adjacent
issues would collide, and porting the file to a durable store before fixing it would make three
known-wrong records durable.

Durability context inherited from #3: the park list is `./.driver-state/parked.jsonl` — relative to
cwd and **gitignored** (`.gitignore:6`), so it cannot travel with the repo and a host change
silently un-parks everything.

## Acceptance criteria

- **C1 (read side).** GIVEN a park log in which issue N was parked and later un-parked, WHEN
  selection computes the park list, THEN N SHALL NOT appear in it, and an issue M parked with no
  later un-park SHALL still appear.
  **CHECK:** extract the real function — `eval "$(sed -n '/^parked_numbers()/,/^}/p' driver/agent-session-driver.sh)"` —
  point `PARKED_LOG` at a fixture containing both cases, and assert only M is printed.

- **C2 (write side).** WHEN a run for a previously-parked issue N reaches a non-parking outcome,
  the driver SHALL record an un-park for N such that C1's read side no longer excludes it.
  **CHECK:** same extraction harness; fixture shape depends on the design decision below, which is
  why this cannot be frozen today.

- **C3 (durability, from #3).** GIVEN issue N parked on host A, WHEN the park list is computed on
  host B whose local `--state-dir` is empty, THEN N SHALL still be excluded from selection.
  **CHECK:** same harness against a seeded durable store plus an empty local state dir.

## Guards

- **G1.** `bash driver/test-driver.sh` — no test lost, newly skipped, or newly failing.
- **G2.** No executable merge path in the driver.
- **G3.** `budget-exhausted` stays **out** of the parking case list.
- **G4.** `make skill-readonly` — the `$SKILL_DIR` deny rules survive.
- **G5.** `--retry N` still bypasses the park skip for one invocation.
- **G6.** The skip reason still cites the *current* park record, not the first appended.
  *(Demoted from a criterion — `tail -1` at `:259` already does this.)*

## Checks as observed at triage (run, not inferred)

| Check | Result today |
|---|---|
| C1 | **FAILS, confirmed two ways.** Extracted the real `parked_numbers` and ran it: → `585 656 710`. Cross-referenced `runs.jsonl`: all three later recorded `gate-eligible`. **Every issue on the effective park list is stale.** The function body is `jq -r '.issue' \| sort -u` — outcome-blind, so *any* un-park record is ignored today, for any design. |
| C3 | **FAILS** — same function against `PARKED_LOG=/nonexistent/fresh-host/parked.jsonl` → empty. The per-machine bug demonstrated directly, not reasoned. |
| C2 | UNRUN — no offline way to exercise the record path; fixture shape undetermined. |
| G2 | **PASSES** — merge-path grep returns nothing. |
| G3 | **PASSES** — parking case list at `:567` and `:685`, neither includes `budget-exhausted`. |
| G4 | **PASSES** — all three deny rules present. |
| G6 | **PASSES** — `tail -1` at `:259`. |
| G1, G5 | UNRUN at scan time; run serially at freeze. |

## Original tier assessment (superseded 2026-07-28)

Was `needs-review`, on the grounds below. Superseded by the decision at the end of this issue —
see the revised tier there. Kept for the reasoning, which is still the record of why the decision
was needed.

**Trigger 1 — a withheld decision that changes which criteria apply.** Two live designs produce
different criteria *and* different fixtures:

- **(A)** append an un-park record and make the reader last-record-wins → needs C1 *and* a
  write-side C2, and C1's fixture must contain an un-park record.
- **(B)** derive the park list from the latest outcome per issue in `runs.jsonl` and stop trusting
  `parked.jsonl` → C2 disappears entirely, and C1's fixture is a `runs.jsonl`.

A check frozen for one design fails a correct implementation of the other. **One human answer
collapses this to a single fixture test and the issue drops to `auto-ok`.**

Trigger 2 does **not** fire: work is confined to `driver/` (+ possibly `docs/`), and
`grep -rn parked skills/` returns nothing. The one adjacency — *"data migration or deletion"* —
fires only if the fix **prunes or rewrites** the existing file rather than appending.

**Open questions:** (1) design A or B — the tier-deciding question; (2) what un-parks —
`gate-eligible` only, or also `gate-human`, a closed issue, a merged PR? (3) repair the four stale
entries or fix forward only? *Pruning is the only branch that touches trigger 2.*

## Implementation notes

- **The frozen check must extract the real function.** `test-driver.sh` mirrors driver logic rather
  than importing it, so a conventionally-styled new test would re-implement last-record-wins in the
  test file and pass with the driver unchanged — exactly "can this pass without the work being
  done?". **#9** is the general fix and is worth sequencing first or alongside.
- Naming `parked_numbers` as the entry point makes the `sed` extraction fail closed under a rename.
- **The parking case list is duplicated** — `:567` (normal) and `:685` (`--classify-only` recovery).
  A write-side fix must touch both; the recovery path is precisely how #656 got its stale record.
- `--retry N` (`:33`, `:92`, `:258`) is a transient, unrecorded un-park and is untested. Don't
  regress it.

## What we're NOT doing

The GHA host (#3).

---
*Criteria + tier added via `agent-session triage`. Checks were run at triage time, not inferred. Original issue text preserved verbatim above; scope widened per the section above.*


---

## Decision (2026-07-28) — D1: derive the park list from `runs.jsonl`

**Resolved: option (B).** Stop trusting `parked.jsonl` as the source of truth; compute the park list
from the **latest outcome per issue** in `runs.jsonl`.

Why this over appending un-park records:

- `runs.jsonl` is already authoritative and already carries `reason`, so the skip line loses nothing.
- Adding a second record type that can drift from `runs.jsonl` reproduces the current bug — **drift
  between those two is what this issue is about.**
- The four stale entries are fixed by construction: nothing to backfill, nothing to prune. **So
  trigger 2 ("data migration or deletion") never fires** — it would have, under the pruning branch.
- Durability becomes one store instead of two, which is why #3's park half was folded in here.

### Consequent changes to the criteria above

- **C2 (write side) is withdrawn.** There is no un-park record to write.
- **C1's fixture is a `runs.jsonl`**, not a `parked.jsonl`: issue N with a later `gate-eligible` row
  must be absent from the park list; issue M whose latest row is `failed`/`incomplete`/`no-gate`
  must be present.
- **C3 (durability)** now means making the *run ledger* durable, not the park file.
- **What un-parks:** any non-parking latest outcome — `gate-eligible` or `gate-human`. Those are
  exactly the outcomes the driver already declines to park.

## Tier: `auto-ok` (revised)

Trigger 1 no longer fires — the withheld design decision is settled, and C1/C3 both reduce to
fixture tests against the real `parked_numbers` extracted from the driver. Trigger 2 does not fire:
work is confined to `driver/`, and the append-only-history problem is dissolved rather than migrated.

**Still required at freeze:** the check must extract the real function
(`sed -n '/^parked_numbers()/,/^}/p'`), not mirror it — see **#9**, and note the parking case list
is duplicated at `:567` and `:685`.




---

## Decision (2026-07-29) — D2: the park record is a GitHub label; the ledger stays history

**Revises D1 in part.** D1's read side stands — stop trusting `parked.jsonl` — but the store is
**GitHub**, not `runs.jsonl`. The park bit becomes a label on the issue (`driver-parked`);
`runs.jsonl` remains the local run history and still supplies the skip line's `reason`, which is
the half of D1 that survives intact.

Why this over deriving the park list from `runs.jsonl`:

- **Selection becomes entirely GitHub-derived.** It already reads marker + tier, open PRs and the
  board column from GitHub; the park list was its *only* local input. Afterwards the local state dir
  holds nothing selection-critical — only per-run debris (`inflight.json`, run transcripts) that is
  intrinsically per-host anyway.
- **Repo scoping by construction.** `parked.jsonl` records no `repo` at all, and `runs.jsonl`
  already mixes two (`agent-sessions #4` sits beside `decafclaw #585`), so a ledger-derived list
  needs a repo filter or it collides across repos on issue number. Labels live on the target repo's
  issues; the collision is unrepresentable.
- **The GHA host (#3) is why durability is in scope, and a tracked ledger is hostile to it.** The
  workflow would have to commit and push state back on every run: bot commits, history churn, and a
  race between concurrent runs. A label is one API call.
- **Visible.** This bug survived because the park list lived in a gitignored file nobody reads. A
  label shows on the issue and on the board — where a human decides whether to `--retry`.
- D1's objection, *"a second record type that can drift from `runs.jsonl`"*, is much weaker for a
  **mutable single bit** than for an append-only log: the last-record-wins fragility that caused
  this bug cannot recur. The framing D1 lacked: **the ledger is history, the label is current
  state**, and conflating those two is the defect itself.

Cost, stated rather than buried: **C2 (the write side) is reinstated** — there is an un-park action
again — and the driver becomes a GitHub *writer* for the first time (`gh label create`,
`gh issue edit --add-label/--remove-label`). None of those is a merge, so `make driver-check` is
unaffected.

### Criteria after D2 — supersedes C1/C2/C3 above

- **C1 (read side).** GIVEN an issue list in which issue N carries the park label and issue M does
  not, WHEN selection computes the park list, THEN N SHALL appear in it and M SHALL NOT.
  **CHECK:** extract the real function —
  `eval "$(sed -n '/^parked_numbers()/,/^}/p' driver/agent-session-driver.sh)"` — feed it a fixture
  `gh issue list --json number,labels` payload carrying both cases, and assert it prints exactly N.

- **C2 (write side — park, both paths).** WHEN a run's outcome is one of
  `parked|failed|incomplete|no-gate`, THE DRIVER SHALL add the park label to that issue, on the
  normal path AND on the `--classify-only` recovery path.
  **CHECK:** invoke the shipped driver as a subprocess once per path with `gh` (and, for the normal
  path, `claude`) stubbed on `PATH` to serve a PR whose gate block reads `verdict: pending`; assert
  the stub's argv log records an add-label call naming the park label and the issue, once per path.

- **C3 (write side — un-park).** WHEN a run's outcome is `gate-eligible` or `gate-human`, THE DRIVER
  SHALL remove the park label from that issue.
  **CHECK:** the same harness with `verdict: eligible-for-auto-merge`; assert a remove-label call
  for that issue and no add-label call.

- **C4 (durability, absorbed from #3).** GIVEN issue N carrying the park label, WHEN selection runs
  with `--state-dir` pointing at an empty directory, THEN N SHALL be reported as skipped with the
  park reason, AND `--retry N` SHALL report it eligible in the same configuration.
  **CHECK:** invoke the shipped driver `--dry-run` as a subprocess against a `gh` stub serving one
  labeled, marker-carrying, `auto-ok` issue and an empty `--state-dir`; assert the `SKIP #N` line,
  then assert `--retry N` yields `ELIGIBLE #N`.

Mapping from the superseded set: old C1 → new C1 (fixture is an issue-list payload, not a
`parked.jsonl` or a `runs.jsonl`); old C2, withdrawn under D1 → reinstated and split into new C2/C3;
old C3 → new C4.

### Guards after D2

- **G1.** `make check` green — `driver-check` + `gate-test` (45 pytest) + `driver-test` (61 bash
  assertions) + `skill-readonly`. No test lost, newly skipped, or newly failing.
- **G2.** No executable merge path in the driver (`make driver-check`).
- **G3.** `budget-exhausted` stays **out** of the parking case list, at both sites.
- **G4.** `make skill-readonly` — the `$SKILL_DIR` deny rules survive.
- **G5** (`--retry` bypass) and **G6** (the skip reason cites the *current* record, not the first
  appended) are **retired as guards and absorbed into C4**, which asserts both behaviourally. They
  could not stay guards across this change: their seeding mechanism is the very store being
  replaced, so their commands would have had to be rewritten mid-run.
- **G7.** `git diff origin/main..HEAD --stat -- skills/ driver/gate.py` is **empty**. Both are
  risk-gated in `CLAUDE.md`; this asserts structurally that the run edited neither the skill nor the
  oracle that grades it.

### What happens to the four stale entries

Nothing, and nothing needs to. **No issue in either repo carries the park label today**, so the
park list starts empty and the stale records are fixed by construction. `parked.jsonl` keeps being
appended as an event log — each entry is *true as history* ("at time T, issue N was parked"); the
bug was reading that history as current state — and nothing reads it for selection any more.
`.driver-state/` stays gitignored. **Trigger 2 ("data migration or deletion") still never fires.**

### Tier after D2 — unchanged, `auto-ok`

Trigger 1 does not fire: the store question is settled here, and C1–C4 all reduce to fixture tests
against the shipped driver. Trigger 2 does not fire: work stays inside `driver/` (+ `Makefile` and
`docs/`), touching neither `skills/**` nor `driver/gate.py`, and the label write is issue *metadata*
— not auth, secrets, data migration/deletion, deploy/infra/CI, or dependencies. The new
outward-facing write was put to the human explicitly (2026-07-29) and accepted, with the boundary
recorded in `CLAUDE.md`: the driver may write issue metadata, never issue or PR content.

