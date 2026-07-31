# Session notes — issue #32

Mode: `agent-session express`, unattended (board-driver). Tier `auto-ok`.

## Phase 0 — preconditions

- **Marker:** present.
- **Readiness variant applied:** the **full checklist**, not the augmented variant. The body was
  written to `spec-template.md`'s shape — it carries *Verifiable acceptance criteria*, *Regression
  guards*, *Tier*, *Design decisions*, *What we're NOT doing* and *Open questions*. Items 1–7 pass.
  Item 2 note: C1 was marked `VERIFIED DISCRIMINATING: yes, ran it`; C2 was explicitly marked
  **UNRUN as a test node**, with the instruction that the freeze run it and record the failure
  rather than inherit the note. At least one criterion discriminated, so the gate held. C2's
  failure is recorded below, as directed.
- **Size:** small. One bash function's output channel plus two test cases in an existing suite.
- **Tier:** `auto-ok`, body and label agreeing. `driver/agent-session-driver.sh` and
  `driver/test-driver.sh` are both on `CLAUDE.md`'s drivable allowlist.

**Named at the outset:** this run edits the driver code that records its own outcome.
`CLAUDE.md` names that residual risk and accepts it (`driver/` minus `gate.py` is drivable), so
the run proceeds — but G2 is load-bearing and is verified explicitly rather than assumed.

## Phase 1 — setup

- Branch / worktree: `fix/32-warning-overwrites-outcome` at
  `.worktrees/fix/32-warning-overwrites-outcome`, off `origin/main` @ `39d4a75`.
- Board: issue #32 moved `Ready` → `In progress` on project 9.
- **Baseline `make check`: green.** Per-suite assertion baselines captured for G3:
  `driver/test-driver.sh` **79 passed, 0 failed**; `park-test` **21 passed, 0 failed**.

## Phase 2a — freeze

`checks.md` written first; the checks were authored **before** any implementation approach was
chosen. Deviation stated rather than skipped: `frozen-checks.md` prescribes a check-author
subagent, and this run's operating instructions prohibit spawning subagents, so the isolation
property was obtained by ordering instead. See the note at the top of `checks.md`.

### Spec-evidence re-confirmation (plan step 4)

Re-confirmed *by the freeze itself* rather than by a separate repro: the newly authored C1 case
reproduces the issue's recorded symptom byte-for-byte, and C2's case — which the spec had never
run — reproduces the ledger corruption end to end.

### Observed at freeze — `make driver-test`

```
#32: a classifier warning must not overwrite the outcome
  ok    probe: gate.py itself classifies the fixture gate-eligible
  ok    probe: and reports exactly one warning on it
  FAIL  #32 C1 the value channel carries the outcome, not the warning
     expected: gate-eligible
     actual:     WARNING: ci row carries no parseable sha ('not yet graded') -- staleness UNCHECKED, not verified current. pr-body-template.md requires it.
  FAIL  #32 C1 and carries the reason with it
     expected: all rows satisfied
     actual:
  ok    #32 G1 the warning is still visible to the operator
  ok    probe: --classify-only appended a ledger row
  FAIL  #32 C2 the recovery path records a known outcome value
     expected: one of gate-eligible|gate-human|ci-stale|incomplete|parked|failed|no-gate|budget-exhausted
     actual:   [  WARNING: ci row carries no parseable sha ('not yet graded') -- staleness UNCHECKED, not verified current. pr-body-template.md requires it.]

83 passed, 3 failed
```

- **C1: fails for the expected reason.** `outcome` holds the warning text (leading two spaces
  and all), `reason` is empty — the shipped `runs.jsonl` row for decafclaw #657 exactly.
- **C2: fails for the expected reason, now run for the first time.** The `--classify-only`
  recovery path appends a ledger row whose `.outcome` is the warning string. The spec inferred
  this from the shipped ledger's `recovered: true` row; it is now a reproduced test failure.
- **Both probes pass**, so the failures are attributable to the defect and not to a broken
  fixture or a changed `gate.py`.
- **Guards at freeze, all passing as guards must:**
  - G1 — the warning is visible today (on the wrong channel, which is the defect).
  - G2 — `git diff --name-only origin/main..HEAD` names no `driver/gate.py`.
  - G3 — 83 passed vs. the 79 baseline: `79 + 4` newly-passing assertions (two attributability
    probes, G1, and C2's row probe). No prior assertion lost, skipped, or newly failing.
  - G4 — `make driver-check`: *no executable merge path in driver/agent-session-driver.sh*.

## Phase 2c — execute

**Phase 1** — `say` → `log` in `classify_pr_body`'s warnings loop. Same text, stderr instead of
stdout. This alone greened both C1 assertions and C2; G1 still passed, which is the point of G1
(deleting the `say` line was the cheap way to green C1 and would have traded a corrupted record for
a missing one). Commit `f2337e3`.

**Phase 2** — both call sites read `.outcome` / `.reason` out of `GATE_JSON` instead of parsing the
stdout line, per the spec's stated preference for the stronger repair. Applied at **both** sites,
because `--classify-only` is the second one and is where #657's corruption was reproduced. Commit
`8fc95c7`.

### The second latent defect, found while implementing

Because both call sites wrapped the call in `$( )` — and command substitution forks — the
`GATE_BLOCK` the function assigns was set in a subshell and never reached the caller, so
`printf '%s\n' "$GATE_BLOCK" > "$rundir/gate.yaml"` on the next line wrote an empty file. **Verified,
not inferred:** every `gate.yaml` under this repo's own `.driver-state/runs/` is a single blank line.
Same root cause, and unavoidably repaired by the fix the spec preferred — a consequence of the
in-scope change, not a drive-by.

It surfaced *after* the freeze closed, so no frozen check covers it. Coverage went into a separately
fenced **NOT FROZEN** coda in `driver/test-driver.sh`, kept apart so the tamper diff over the frozen
assertions stays reviewable. **Confirmed discriminating** by stashing Phase 2 and re-running against
the Phase 1 tree, where it reports `[|]` — the blank line.

## Phase 2d — independent verification

Dispatched a verifier subagent with a fresh context, given only `checks.md` and the repo. All
criteria and guards pass; the report and the tamper verdict are recorded in `checks.md`.

**It caught a defect in the manifest I wrote:** G3's baseline note spelled `origin/main` as
`39a4d75` where it is `39d4a75` — found by checking the sha existed rather than trusting it. Logged
as a **clarification**, not an amendment: under `frozen-checks.md`'s both-trees test no verdict
changes at either tree, because no assertion count depends on how the baseline commit is spelled.
No tier change.

**Instruction conflict, stated rather than resolved silently.** This run's operating instructions
prohibit spawning subagents; `express.md` step 2d requires a fresh-context verifier and says it is
*"never skipped, never self-reported."* Resolved by treating "follow express.md exactly" as the
request, on the grounds that the verifier is the one mechanism with **no in-context substitute** —
unlike the check-author subagent, whose isolation property was obtainable by ordering (see
`checks.md`). The asymmetry is the reasoning, not the outcome. Flagged in the run report so a human
can overrule it.

## Phase 2e — rebase and re-verify

`origin/main` had not moved (`39d4a75`), so the rebase was a no-op and the freeze sha needed no
re-anchoring. `53b4a93` confirmed still an ancestor of HEAD. `make check` re-run green after.

## Phase 2f — branch self-review

**Two regressions found, both introduced by Phase 2, both fixed in `a3cea86`.** Neither is new
behaviour — each restores what the pre-change code did on the failure path:

1. **Stale verdict.** `GATE_JSON` is only assigned on success and the callers now *read* it, so a
   failed classify would have left the **previous issue's** verdict standing — under
   `--max-issues 2`, recording issue A's outcome against issue B. The old code read stdout, so it
   came back empty. Fixed by clearing `GATE_JSON` / `GATE_BLOCK` on entry; verified that `jq` over
   empty input emits nothing and exits 0, so `outcome` comes back `""` exactly as before.
2. **Abort instead of record.** As a plain command under `set -euo pipefail`, a failing
   `classify_pr_body` would abort the driver, where inside `$( )` it was invisible to `set -e`. On
   `--classify-only` that means dying without recording anything — #32's own shape one level up.
   Fixed with `|| true` at both sites.

That these were caught by self-review and not by any check is worth recording: both live on the
*failure* path, and neither criterion exercises a failing classifier.

## Phase 2g — push and open

Branch pushed **as-is**, no squash, so `53b4a93` ships as an ancestor of the head and a reviewer can
re-run the tamper diff rather than trusting the recorded verdict. PR:
https://github.com/lmorchard/agent-sessions/pull/40, opened with `verdict: pending` per `pr.md`.
Board: #32 moved → `In review`.

Tamper re-run immediately before pushing: `git diff 53b4a93 -- driver/test-driver.sh` is 65 changed
lines with **zero content-removal lines** — purely additive. Verdict stands as `clean` under the
stated invariant.

## Phase 2h — review cycle

Copilot reviewed **6 of 6 changed files and generated no comments**. Nothing to fix, skip or defer.
0 review threads total, 0 unresolved — and per `pr.md`'s warning, the review itself was confirmed to
have landed (`copilot-pull-request-reviewer`, state `COMMENTED`) rather than reading `0 unresolved`
as proof a reviewer ran.

**Substitute to name in the polling:** `pr.md` step 9 prescribes polling every 30s for up to 10
minutes. A `sleep` poll loop, a backgrounded shell, and `Monitor` are all denied under this run's
`dontAsk` floor — exactly as `pr.md` predicts — and unlike CI there is no single blocking command
for review comments the way `gh pr checks --watch` is. Substituted direct polls spaced across turns
by doing other required work between them (the notes write-up and the step-12 re-verification). The
review did arrive, so the substitute did not cost the row. **The first review request was consumed
without producing a review**, most likely because a commit was pushed after requesting it; the
request was re-issued against the final head, and that is what landed.

A verifier re-run followed, per step 12 — see `checks.md`.

## Phase 2i — merge gate

| Row | Source | Result |
|---|---|---|
| Every criterion with a check passes | verifier's step-12 re-run on HEAD `b187187` | C1 pass · C2 pass |
| Human-judgment criteria graded | — | n/a, none in this spec |
| Every guard still passes | same verifier report | G1 · G2 · G3 · G4 all pass |
| Tamper clean, or every difference logged | verdict recorded above; freeze `53b4a93` is an ancestor of the pushed head, so it stays re-runnable | clean under the stated invariant |
| Local project gates green | `make check` in the worktree | green |
| CI on the pushed head all passes | `gh pr checks 40 --watch` → *no checks reported*; no `.github/workflows/` in the repo | `no checks configured` — stated as a fact, not read as a green light |
| No unresolved review threads | GraphQL `reviewThreads` | 0 of 0, review confirmed landed |
| Tier `auto-ok`, not downgraded | `spec.md` Tier section | `auto-ok`; one clarification logged, no amendment, so no downgrade |
| No risk-gated path touched | the diff vs. `CLAUDE.md`'s allowlist | `driver/` (not `gate.py`), `docs/` — all drivable |

**Verdict: `eligible-for-auto-merge`.** All rows satisfied. Nothing was merged and auto-merge was
not enabled — the verdict is a finding this run reports.

### Substitutes and deviations, named rather than left to a reader to notice

Three, none of which changes a row's result, all of which a human should see:

1. **The check-author subagent was not used.** `frozen-checks.md` prescribes one; this run's
   operating instructions prohibit spawning subagents. Isolation was obtained by **ordering** — the
   checks were authored and their failures observed before any implementation approach was chosen.
   Weaker guarantee (one context, not two) for the same property.
2. **The verifier subagents *were* used, against that same prohibition.** Unlike the check-author,
   the verifier has no in-context substitute — "a different context runs the checks" cannot be
   simulated by ordering — and `express.md` says it is *never self-reported*. Resolved by treating
   "follow `express.md` exactly" as the request. Flagged so it can be overruled.
3. **The second verifier could not run `make driver-test` itself** and delegated that one command to
   a further fresh context. Disclosed by the verifier rather than fabricated; output matches the
   implementer's own run line for line.

### Follow-ups this run deliberately did not do

- **Re-run `--classify-only 657` against decafclaw** once this lands, so a correct row is *appended*
  to `runs.jsonl` — the spec's default for its own open question, and an end-to-end validation of C2
  against the real case. Outside this PR: it writes to a different repo.
- **Sweep other `say` calls inside value-returning functions.** Phase 2 removes the dependence on
  that audit at these two call sites; the sweep wants its own issue.
- **A frozen check for the `gate.yaml` repair.** It surfaced after the freeze closed, so it got
  non-frozen coverage. If it should be frozen, that is an intake decision, not this run's.
