# Report marker-less issues at select — Implementation Plan

**Goal:** the select stage accounts for every open issue it read, so an untriaged issue renders as
something rather than as nothing.

**Source issue:** https://github.com/lmorchard/agent-sessions/issues/13 — **Tier:** `auto-ok`
(every criterion machine-graded on generated stdout; the change is confined to
`driver/agent-session-driver.sh`, which `CLAUDE.md` lists as drivable)

**Approach:** take the marker-less set as the **complement** of `tier_batch`'s emitted numbers — never
a second `jq` implementation of the marker predicate — and append it as a parenthetical to the
existing `read N open issues` line. No cap on the list.

**Criteria:** C1 — a mixed queue emits every marker-less issue number and lists none of them as
`ELIGIBLE`. (Full text + checks in `checks.md`.)

---

## Phase 0: Freeze the acceptance checks — **DONE**

**Files:**
- Created: `docs/dev-sessions/2026-07-29-1730-13-marker-less-report/checks.md`
- Modified: `driver/test-driver.sh:575-702` — the C1 case and the G1 guard case

**Verification — automated:**
- [x] C1's check runs and **fails for the expected reason** — assertion (a); liveness probe passing
      is what makes it attributable. Recorded in `checks.md`.
- [x] Guards run and pass — G1 directly; G3 via `test-driver.sh:577-578`; G4 via `make check` at
      session setup (this discharges the issue's standing "UNRUN, must be run before merge"); G2
      discharged by proxy, stated as such in `checks.md`.
- [x] Freeze commit `8438711`; sha recorded in follow-up commit `6c891a3`.

---

## Phase 1: Account for the marker-less set on the count line — **DONE, BLOCKED AT VERIFICATION**

**Advances:** C1 (fully — all three assertions pass).

**Files:**
- Modified: `driver/agent-session-driver.sh:360-410` — `select_issues`

**Key changes:**
- `tier-batch` invocation moved **ahead of** the count line. The complement cannot be taken before
  the candidate list exists, and the count line is where the accounting belongs. It reads only
  `issues_json`, so nothing below it was depended on.
- Complement derived in `jq` from `tier-batch`'s own output:

```bash
specced_nums="$(printf '%s' "$candidates" | cut -f1 | tr '\n' ' ')"
markerless_nums="$(printf '%s' "$issues_json" | jq -r --arg keep "$specced_nums" '
    ($keep | split(" ") | map(select(length > 0))) as $k
    | .[] | .number | tostring | . as $n
    | select(($k | index($n)) == null)')"
```

  `. as $n` is load-bearing. In `index(f)`, `f` is evaluated against `index`'s **own input**, so the
  tempting `index(.)` searches the keep-list for itself, matches every time, and yields an empty
  complement — a reporter that says "nothing missing" unconditionally. This was written the wrong way
  first and caught by running it; it is the same null-renders-as-positive shape the issue is about.

- Conditional emit — the parenthetical appears only when the set is non-empty, which is what makes a
  separate line unnecessary.

**Verification — automated:**
- [x] C1 (a) the marker-less number appears: **passes**
- [x] C1 (b) no `ELIGIBLE` line names it: **passes**
- [x] C1 (c) the run reports `eligible: 1`: **passes**
- [x] G1 zero-marker message intact: **passes**
- [x] G3 `bash -n` (suite's `syntax` case): **passes**
- [x] G2 path half — `git diff 8438711 --stat` shows `driver/gate.py` untouched
- [ ] **`make driver-test` green — NO. 68 passed, 1 failed.** The one failure is the frozen liveness
      probe, which exact-matches the count line this change is specified to modify. **This is an
      amendment and it stops for a human.** See `notes.md`.
- [ ] `make check` green — not reached; blocked by the above.

**Verification — manual:**
- [x] Live `make dry-run-self`: prints `read 15 open issues` with no parenthetical. Verified correct
      rather than assumed — `gh issue list` reports 15 of 15 carrying the marker, none without.

---

## Phase 2: not planned

The work is one slice. No second phase was needed, and none is proposed: the remaining item is a
decision, not an implementation step.
