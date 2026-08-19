# #32 — a classifier warning must not overwrite the outcome · Implementation Plan

**Goal:** separate the warning channel from the value channel around `classify_pr_body`, so a run
that triggers a warning still records what the gate decided.

**Source issue:** https://github.com/lmorchard/agent-sessions/issues/32 — **Tier:** `auto-ok`
(every criterion is a runnable check; the work is confined to `driver/agent-session-driver.sh`
and `driver/test-driver.sh`, both on `CLAUDE.md`'s drivable allowlist; `driver/gate.py` is
guarded against by G2).

**Approach:** the spec's Design decision — treat this as channel separation, not formatting — and
its stated preference for the stronger of the two named repairs. Both are taken, because they close
different halves: the warning moves off stdout so the function honours the contract in its own
comment, **and** the two call sites stop parsing stdout entirely and read the JSON that
`GATE_JSON` already holds, which removes the shared channel rather than merely vacating it.

**Criteria:** C1 the value channel carries the outcome, not the warning · C2 the
`--classify-only` recovery path records a valid outcome.
Full text + checks live in `checks.md`. Ids assigned there.

---

## Phase 0: Freeze the acceptance checks — **DONE**

**Files:**
- Created: `docs/archive/dev-sessions/2026-07-31-0741-32-warning-overwrites-outcome/checks.md`
- Modified: `driver/test-driver.sh` — the `#32` section, C1 + C2 + G1 + two attributability probes

**Verification — automated:**
- [x] C1's check runs and fails for the expected reason — `outcome` holds the warning text,
      `reason` is empty, matching the shipped decafclaw #657 ledger row. Output in `notes.md`.
- [x] C2's check runs and fails for the expected reason — the appended `runs.jsonl` row's
      `.outcome` is the warning string. The spec had this **UNRUN**; the freeze ran it.
- [x] Both attributability probes pass, so the failures are the defect and not a broken fixture.
- [x] Guards run and pass: G1 (warning visible today), G2 (no `gate.py` in the diff), G3
      (83 = 79 baseline + 4 new passing; nothing lost), G4 (`no executable merge path`).
- [x] Freeze commit `53b4a93`; sha recorded in `checks.md` by follow-up commit `334f0b1`.

---

## Phase 1: Move the warning off the value channel

`classify_pr_body`'s comment says *"Prints `outcome<TAB>reason`"* — its stdout is its return value.
`say()` writes to stdout; `log()` and `die()` both redirect to stderr. The warning loop uses `say`,
so a warning becomes line 1 of the return value and `read -r` takes it as the outcome.

**Advances:** C1 (fully — C1 asserts over the function's own stdout contract). Partially C2: this
alone would also green C2, but Phase 2 is what stops the next `say` added inside this function from
re-breaking both, which is the spec's Design decision and the reason C2 is a separate criterion.

**Files:**
- Modify: `driver/agent-session-driver.sh` — the warnings loop inside `classify_pr_body`

**Key changes:**

`say` → `log` in the warnings loop only. `log` timestamps and redirects to stderr, which is where
a diagnostic belongs when the function's stdout is a value. The warning text is unchanged, so G1's
needle still matches; only the fd changes.

```bash
  # Warnings are the parser's "a null must never render as a positive" channel.
  # `log`, never `say`: this function's stdout IS its return value (see the
  # comment above), and `say` writes to stdout -- which is how a warning came to
  # overwrite the outcome it was warning about on decafclaw #657. See issue #32.
  printf '%s' "$GATE_JSON" | jq -r '.warnings[]?' | while IFS= read -r w; do
    log "  WARNING: $w"
  done
```

**Verification — automated:**
- [ ] C1's check passes: `make driver-test` — `#32 C1 the value channel carries the outcome, not
      the warning` and `#32 C1 and carries the reason with it`
- [ ] G1 still passes: `make driver-test` — `#32 G1 the warning is still visible to the operator`
- [ ] `make driver-check` passes (G4)

---

## Phase 2: Take the callers off the shared channel

The remaining fragility is structural: *any* stdout write inside `classify_pr_body` corrupts its
return value, so Phase 1 fixes this warning and leaves the landmine. The spec's Design decision
names the stronger repair — *"the caller stops parsing stdout and reads the JSON that `GATE_JSON`
already holds"* — and this phase applies it at **both** call sites, because a fix at one and not
the other is `docs/findings.md` class 1's "fixed the cost field, never generalised".

**Advances:** C2 (fully, at both call sites). Reinforces C1.

**Files:**
- Modify: `driver/agent-session-driver.sh` — the run path's call site and the `--classify-only`
  recovery path's call site
- Test: `driver/test-driver.sh` — one **non-frozen** assertion for the `gate.yaml` repair below.
  The `#32` C1/C2/G1 assertions are frozen and read-only from here on.

**Key changes:**

Both call sites currently read:

```bash
IFS="$(printf '\t')" read -r outcome reason <<EOF
$(classify_pr_body "$_body" "$GATE_HEAD_SHA")
EOF
```

and become:

```bash
# NOT `$(classify_pr_body ...)`: command substitution forks, so the GATE_JSON and
# GATE_BLOCK the function sets would be assigned in a subshell and lost. Calling
# it plainly keeps them, and reading the fields is what removes the shared
# stdout channel that broke this on decafclaw #657. See issue #32.
classify_pr_body "$_body" "$GATE_HEAD_SHA" >/dev/null
outcome="$(printf '%s' "$GATE_JSON" | jq -r '.outcome')"
reason="$(printf '%s' "$GATE_JSON" | jq -r '.reason')"
```

**A second latent defect this repairs, stated rather than smuggled.** Because the call was inside
`$( )`, `GATE_BLOCK` was assigned in a subshell and never reached the caller — so
`printf '%s\n' "$GATE_BLOCK" > "$rundir/gate.yaml"` on the next line has been writing an **empty
file on every real run**. Verified, not inferred: every `gate.yaml` under this repo's own
`.driver-state/runs/` is one blank line. It is the same root cause (results funnelled through a
subshell'd stdout) and it is unavoidably repaired by the fix the spec prefers, so it is a
consequence of the in-scope change rather than a drive-by. No frozen check covers it — the freeze
is closed — so it gets non-frozen coverage below and a line in the PR body.

**Plan self-review finding, resolved and recorded.** After Phase 2 no production caller reads the
function's stdout, so the `outcome<TAB>reason` print is used only by C1. That is deliberate and the
freeze is what makes it so: C1 was authored to assert the contract in the function's own comment,
and the read-only rule means the contract must now be honoured, not deleted. The alternative —
dropping the print and rewriting C1 — is editing the oracle to suit the implementation, which is
the one move this whole mechanism exists to prevent. So the print stays, its comment stays true,
and the callers use the richer JSON. Stdout is redirected to `/dev/null` at both call sites rather
than left to print, because the driver already emits `outcome`/`reason` on labelled lines two lines
later and a bare tab-separated duplicate is noise.

**Verification — automated:**
- [ ] C1's checks still pass: `make driver-test` — both `#32 C1` assertions
- [ ] C2's check passes: `make driver-test` — `#32 C2 the recovery path records a known outcome
      value`
- [ ] G1 still passes: `make driver-test` — `#32 G1 the warning is still visible to the operator`
- [ ] New non-frozen assertion passes: `gate.yaml` is written non-empty when a run dir exists
- [ ] G3: `make driver-test` — no prior assertion lost, skipped, or newly failing, against the
      **79 passed, 0 failed** baseline in `checks.md`
- [ ] G2: `git diff --name-only origin/main..HEAD` names no `driver/gate.py`
- [ ] G4: `make driver-check` passes
- [ ] `make check` green (includes `docs-check`, `skill-readonly`, `park-test`)

---

## Phase 3: Session notes

**Advances:** no criterion — documentation of the run, not behaviour. Listed explicitly so the
bidirectional-coverage rule is satisfied by a stated exception rather than by an omission.

**Files:**
- Modify: `docs/archive/dev-sessions/2026-07-31-0741-32-warning-overwrites-outcome/notes.md` — the
  execution record, the verifier's report, and the tamper verdict

**Verification — automated:**
- [ ] `make docs-check` passes

---

## Scope discipline

Explicitly **not** doing, per the spec's *What we're NOT doing*:

- Silencing the warning (G1 exists to catch that).
- Touching `driver/gate.py` (G2).
- Rewriting the two corrupted #657 rows in `runs.jsonl` — append-only history. The spec's default
  is to re-run `--classify-only 657` after the fix lands so a correct row is *appended*. That is a
  **post-merge action against the decafclaw repo**, outside this PR and outside this run.
- Auditing every other `say` inside a value-returning function. Phase 2 removes the *dependence*
  on that audit at these two call sites, but the sweep itself stays a separate issue.
