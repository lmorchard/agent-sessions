# `fetch_open_prs` stops swallowing gh failures — Implementation Plan

**Goal:** make a failed open-PR query distinguishable from "there are no open PRs", and make each
caller take the trade that fits its own cost.

**Source issue:** https://github.com/lmorchard/agent-sessions/issues/39 — **Tier:** `auto-ok`
(all three criteria are assertions in an existing bash fixture harness; the work lands in
`driver/agent-session-driver.sh` and `driver/test-park-state.sh`, both on CLAUDE.md's drivable
allowlist)

**Approach:** `fetch_open_prs` stops discarding stderr and stops converting failure into `[]`; it
propagates `gh`'s stderr and exit status and nothing else. Callers then split: **selection refuses**
(the failure precedes all spend, and proceeding on an empty list is a guess that buys a duplicate
$5–20 run), **discovery degrades distinguishably** (the money is already spent and a PR may exist,
so refusing would destroy the only record of it). No `--json` field-list fallback — the strict
matcher reads `closingIssuesReferences`, so a response served without it matches nothing, exactly
as an empty list does.

**Criteria:** C1 selection reports the failure, exits non-zero, invokes `claude` zero times ·
C2 discovery's recorded reason names the query failure and is not `no PR opened` · C3 `gh`'s
stderr reaches the driver's output.
*(Full text + checks in `checks.md`. The string the implementation must emit is
`open-PR query failed`, fixed at the freeze.)*

**Standing constraint for every phase below:** `driver/test-park-state.sh` is **read-only from
Phase 1 onward** (frozen at `cc45871`). A failing frozen check is a report-back, not a fix-up.

**Shell constraint that shapes the code:** the driver runs under `set -euo pipefail`. So
`cond && var="$(...)"` is a trap — when `cond` is false the compound returns non-zero and `set -e`
aborts. Every conditional assignment below uses `if/then/fi` for that reason, not for style.

---

## Phase 0: Freeze the acceptance checks — DONE

Frozen at `cc45871`, sha recorded in `5a91662`.

**Files:**
- Created: `docs/dev-sessions/2026-07-31-1739-39-fetch-open-prs-failures/checks.md`
- Modified: `driver/test-park-state.sh` — the three cases C1–C3 name, plus a control case and one
  argv-logging line in the `claude` stub without which C1's zero-count clause is vacuous

**Verification — automated:**
- [x] Every criterion's check runs and **fails for the expected reason** — 6 new assertions fail,
      each quoted in `checks.md` with why it is attributable to the absent behaviour
- [x] Every guard runs and **passes** — `make driver-test` 112/0, `make assertion-lint` green,
      all 22 pre-existing park assertions unchanged
- [x] Freeze commit made; sha recorded in `checks.md`

---

## Phase 1: `fetch_open_prs` propagates failure instead of manufacturing an empty list

The one-line root change, plus the two guarded call sites that must not break under `set -e` when
it starts being able to fail. Delivered as one slice because the change is not separable: the
moment `fetch_open_prs` can return non-zero, every unguarded caller aborts the script, so shipping
the function change without the call sites would leave the tree broken between commits.

**Advances:** C1, C2, C3 — all three. C3 falls out of the function change alone; C1 out of the
selection call site; C2 out of the two discovery call sites.

**Files:**
- Modify: `driver/agent-session-driver.sh` — `fetch_open_prs` (`:487-490`), the selection call site
  (`:606`), the `run_issue` discovery call site (`:882`), the `--classify-only` discovery call site
  (`:1023`)
- Test: none of this slice's own. The frozen cases in `driver/test-park-state.sh` are the
  verification, and they are read-only.

**Key changes:**

**1. `fetch_open_prs` (`:487-490`)** — delete the swallow. Keep the existing comment about
`closingIssuesReferences` riding along for free; append the reason the swallow is gone.

```bash
fetch_open_prs() {
  gh pr list --repo "$REPO" --state open --limit 200 \
     --json number,title,body,headRefName,url,closingIssuesReferences
}
```

`gh`'s stderr now reaches the driver's stderr untouched (that is C3), and the exit status reaches
the caller (that is what C1 and C2 route on). Nothing else changes: on success the function still
prints the parsed list and exits 0, which is G3.

**2. Selection refuses (`:606`, inside `select_issues`)** — `select_issues` is called plainly at
`:1072`, not inside `$( )`, so `die` exits the script with 2 rather than a subshell.

```bash
  local prs parked
  prs="$(fetch_open_prs)" \
    || die "open-PR query failed -- cannot tell which issues already have open PRs, so selection would be a guess. Refusing to select. (gh's own error is above.)"
```

`die` writes `error: <msg>` to stderr and exits 2, which is C1's three clauses at once: the message
carries the needle, the status is non-zero, and the run loop at `:1094` is never reached.

**3. Discovery degrades, in `run_issue` (`:882`)** — the opposite trade, deliberately.

```bash
    local prs_json pr_query_failed=0
    prs_json="$(fetch_open_prs)" || pr_query_failed=1
    prline=""
    if [ "$pr_query_failed" -eq 0 ]; then
      prline="$(pr_for_issue "$n" "$prs_json")"
    fi
    if [ -z "$prline" ]; then
      outcome="parked"
      if [ "$pr_query_failed" -eq 1 ]; then
        reason="open-PR query failed; cannot tell whether a PR was opened. run's own account: $(printf '%s' "$final" | tr '\n' ' ' | cut -c1-400)"
      else
        reason="no PR opened; run's own account: $(printf '%s' "$final" | tr '\n' ' ' | cut -c1-400)"
      fi
    else
```

The outcome stays `parked` in both branches — only the reason differs. That is the point: the run
did happen and cost money, so it keeps its ledger row; what changes is that the row stops asserting
something the driver could not observe.

**4. The same fix at `--classify-only` (`:1023`, top-level — no `local`).** Its reason string is a
different literal (`no open PR found for #$n`), so C2's fixture does not reach it. Fixing it anyway
because fixing one call site and not its twin is `findings.md` class 1 — "fixed the cost field,
never generalised" — and the driver's own comment at `:1032-1036` says this is the call site that
matters most, being the documented recovery path.

```bash
_prs_json=""; _pr_query_failed=0
_prs_json="$(fetch_open_prs)" || _pr_query_failed=1
prline=""
if [ "$_pr_query_failed" -eq 0 ]; then
  prline="$(pr_for_issue "$n" "$_prs_json")"
fi
if [ -z "$prline" ]; then
  outcome="parked"
  if [ "$_pr_query_failed" -eq 1 ]; then
    reason="open-PR query failed; cannot tell whether #$n has an open PR"
  else
    reason="no open PR found for #$n"
  fi
  prurl=""
else
```

**Verification — automated:**
- [x] C1's check passes: `make park-test` — `selection names the open-PR query failure`,
      `and exits non-zero`, `and never invokes claude`, plus the control
      `with a healthy query the same run DOES invoke claude`
- [x] C2's check passes: `make park-test` — `the recorded reason names the query failure` and
      `and is not the no-PR-opened reason`
- [x] C3's check passes: `make park-test` — `gh's stderr reaches the driver's output`
- [x] G1 still passes: `make driver-test` (112 passed, 0 failed) and `make park-test` — no case
      lost, newly skipped, or newly failing
- [x] G2 still passes: `make assertion-lint`
- [x] G3 still passes: `make park-test` — the 22 pre-existing assertions unchanged
- [x] `make check` exits 0
- [x] Tamper diff empty: `git diff cc45871 -- driver/test-park-state.sh`

**Observed:** `make park-test` → `28 passed, 0 failed` (22 pre-existing + the 6 frozen assertions,
all six of which failed at the freeze). `make check` → `all checks passed`. Tamper diff → empty
output.

**Verification — manual:**
- [ ] None. Every criterion is machine-checkable; that is why this issue is `auto-ok`.

---

## Coverage check (both directions)

| | C1 | C2 | C3 |
|---|---|---|---|
| Phase 1 | ✓ | ✓ | ✓ |

Every criterion is advanced by a phase, and the one implementation phase advances all three. No
phase advances nothing.

## Out of scope for this plan

Carried from the spec's *What we're NOT doing*, restated because a plan read on its own has to
hold its own boundary: no retry, no `--json` field-list fallback, no touching `driver/gate.py`,
no re-unifying the two matchers, and no widening this to the driver's other `gh` calls (real, and
a separate issue).
