**Goal:** stop a classifier *warning* from overwriting the classifier's *outcome*, so a run that
triggers a warning still records what the gate decided.

**Source:** https://github.com/lmorchard/agent-sessions/issues/32 — hit for real on 2026-07-29 by the
run on decafclaw #657 — a **$16.69** run, the most expensive on record, whose outcome was never
recorded.

## What happened

The ledger row for #657 reads:

```
issue:    657
cost_usd: 16.68997699999999
pr:       https://github.com/lmorchard/decafclaw/pull/728
outcome:    WARNING: ci row carries no parseable sha ('not yet graded') -- staleness UNCHECKED, not verified current. pr-body-template.md requires it.
reason:
```

The `outcome` field holds a warning string and `reason` is empty. The row appears **twice**, the
second carrying `recovered: true` — so `--classify-only 657` was run afterwards and **reproduced the
same corruption.**

The verdict was recovered by hand, by classifying the PR body directly: `outcome = incomplete`,
*"verdict still pending -- run did not reach the gate."* PR 728 publishes `verdict: pending`,
`ci: not yet graded`, `threads: not yet queried`. So nothing merge-worthy was sitting unnoticed — but
the driver could not say so.

## Root cause, confirmed by reproduction

`classify_pr_body()` (`agent-session-driver.sh:443`) documents itself as *"Prints
`outcome<TAB>reason`"* — its **stdout is its return value**. Inside it, the warnings loop does:

```bash
printf '%s' "$GATE_JSON" | jq -r '.warnings[]?' | while IFS= read -r w; do
  say "  WARNING: $w"
done
printf '%s' "$GATE_JSON" | jq -r '[.outcome, .reason] | @tsv'
```

`say()` at `:65` writes to **stdout** — unlike `log()` and `die()`, which both redirect to stderr.
Both call sites (`:632` in the run path, `:756` in `--classify-only`) then do:

```bash
IFS=$'\t' read -r outcome reason <<EOF
$(classify_pr_body "$_body" "$GATE_HEAD_SHA")
EOF
```

`read -r` consumes **only the first line**. When a warning fires it becomes line 1, contains no tab,
so `outcome` swallows the whole warning and the real `outcome<TAB>reason` line is discarded unread.

**`driver/gate.py` is correct and needs no change.** It puts warnings in a structured `warnings` array
and the outcome in `outcome`; the same fixture through `gate.py` directly yields
`outcome = gate-eligible, reason = all rows satisfied`. The defect is entirely in the bash wrapper
mixing a warning channel into a value channel.

## Why this is worse than it looks

- **The documented recovery path reproduces it.** `:756` is `--classify-only`, so the tool that exists
  to recover an unrecorded outcome records the same corrupted one. Proved by row 3's
  `recovered: true`.
- **It only fires when a warning fires**, so eight prior runs were clean. Latent since the warning
  channel was added, and it surfaced the first time the ci-sha warning ever fired in anger.
- **The warning exists *because* of "a null must never render as a positive"** (`docs/findings.md`
  defect class 2) — and the mechanism built to prevent that class is what destroyed the value. It is
  also class 1: the `outcome` field is populated, so the row *looks* complete.
- Under phase 3 it fails **safe** — a warning string does not match `gate-eligible`, so nothing would
  auto-merge — but the record is destroyed and unrecoverable by the built-in path.

## Verifiable acceptance criteria

- **C1.** WHEN the classifier emits a warning, the driver SHALL record the gate's outcome and reason,
  and SHALL NOT record any part of the warning text in the `outcome` field.
  **CHECK:** a new case in `driver/test-driver.sh` invoking the shipped `classify_pr_body` (extracted
  by the `driver/test-park-state.sh:180` pattern, which runs the shipped text rather than a copy) with
  a gate block whose `ci` row is `not yet graded` and a non-empty head sha, then asserting
  `outcome == "gate-eligible"` and `reason == "all rows satisfied"`.
  **VERIFIED DISCRIMINATING:** yes, ran it. Today the same invocation yields
  `outcome = [  WARNING: ci row carries no parseable sha ('not yet graded') -- staleness UNCHECKED, not verified current. pr-body-template.md requires it.]`
  and `reason = []`, matching the shipped ledger row exactly. The same fixture through
  `python3 driver/gate.py classify` yields `gate-eligible` / `all rows satisfied`, so the correct
  answer is available and simply discarded.

- **C2.** WHEN `--classify-only` runs against a PR whose gate triggers a warning, THEN the row it
  appends to `runs.jsonl` SHALL carry a valid outcome.
  **CHECK:** a case using the offline `gh`-stub pattern at `driver/test-driver.sh:456-487` to serve a
  PR body with an unparseable `ci` sha, invoking `--classify-only <n>` against a temp `--state-dir`,
  and asserting the appended row's `.outcome` is one of the known outcome values.
  **VERIFIED DISCRIMINATING:** the live evidence is the shipped ledger — row 3 for #657 carries
  `recovered: true` and the corrupted outcome, so this path is confirmed broken. **UNRUN as a test
  node** (it does not exist); the freeze must run it and record the failure rather than inherit this
  note. It is a *separate* criterion from C1 because it is a *second call site*, and a fix applied at
  one and not the other is the "fixed the cost field, never generalised" pattern `docs/findings.md`
  class 1 names as why this class recurs.

## Regression guards

- **G1.** The warning is still visible to the operator after the fix. **This is the guard that matters
  most:** the cheapest way to green C1 is to delete the `say` line, which silences a
  null-must-not-render-as-positive warning — trading a corrupted record for a missing one.
  **CHECK:** the same invocation as C1 still emits the warning text somewhere the operator sees
  (stderr, or the run report). Passes today, wrongly placed.
- **G2.** `driver/gate.py` is unchanged by this work. **Load-bearing for the tier:** `gate.py` is
  risk-gated in `CLAUDE.md`, so if the fix reaches into it, trigger 2 fires and the `auto-ok` below is
  void. `gate.py` is already correct, so there is no reason to touch it.
  **CHECK:** `git diff --name-only origin/main..HEAD` contains no `driver/gate.py`. Passes today.
- **G3.** `make driver-test` — no assertion lost, newly skipped, or newly failing. Invariant, not a
  count.
- **G4.** `make driver-check` — the driver still has no executable merge path.

## Tier: `auto-ok`

**Trigger 1 does not fire.** C1's oracle exists and was run; the correct answer is already produced by
`gate.py`, so nothing must be decided to know what "right" means. The two plausible fixes — route
`say` to stderr inside that function, or have the callers read the JSON fields instead of parsing
stdout lines — are implementation style: both criteria hold unchanged under either, so
`acceptance-criteria.md`'s "does the choice change which criteria apply?" answers no.

**Trigger 2 does not fire.** The work touches `driver/agent-session-driver.sh` and
`driver/test-driver.sh`, both drivable under `CLAUDE.md`'s allowlist. It must **not** touch
`driver/gate.py` (G2). No auth, secrets, data migration/deletion, deploy/infra/CI config or dependency
change; no issue or PR content is written.

## Design decisions

- **Decision:** treat this as a channel-separation bug, not a formatting bug.
  - **Why:** the function's contract is "stdout is the value." Anything that writes to stdout inside
    it is a defect regardless of what it says, so the fix should make that structurally impossible —
    either the warning goes to stderr, or the caller stops parsing stdout and reads the JSON that
    `GATE_JSON` already holds. The second is stronger: it removes the shared channel entirely.
  - **Rejected:** making the caller skip lines that look like warnings, which re-creates the same
    fragility one layer up.

- **Decision:** `driver/gate.py` is out of scope and guarded against.
  - **Why:** it is already correct, and it is a risk-gated path — touching it would make this issue
    `needs-review` for no benefit.

## What we're NOT doing

- **Silencing the warning.** See G1. A missing warning is not better than a misplaced one.
- **Changing `driver/gate.py`.** See G2.
- **Rewriting the two corrupted #657 rows in `runs.jsonl`.** It is append-only history; see Open
  questions.
- **Auditing every other `say` in the driver for the same shape.** Tempting, and probably worth its own
  issue, but it widens this one past the criteria above. If a scan is wanted, file it separately.

## Open questions

- **Do the two corrupted #657 rows get corrected?** They are history, and `runs.jsonl` is append-only.
  **Default:** leave them, and once the fix lands, re-run `--classify-only 657` so a correct row is
  *appended* — which doubles as an end-to-end validation of C2 against the real case that produced the
  bug. Note the recovered value for the record: `incomplete`, *"verdict still pending -- run did not
  reach the gate."*
- **Are there other `say` calls inside functions whose stdout is a return value?** Not audited. **Default:**
  out of scope here (see What we're NOT doing); file a separate sweep if wanted. Related to
  `docs/findings.md` class 1's standing "nobody has ever looked" gap, one layer down.
