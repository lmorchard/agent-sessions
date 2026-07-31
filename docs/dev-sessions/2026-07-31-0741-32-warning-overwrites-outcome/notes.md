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
