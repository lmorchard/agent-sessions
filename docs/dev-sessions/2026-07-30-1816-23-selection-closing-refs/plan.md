# Selection blocks on a closing link, not a mention — Implementation Plan

**Goal:** at the selection gate, an issue counts as "already has an open PR" only when an open PR
declares it via `closingIssuesReferences`; a bare `#N` in prose or a number in a branch name no
longer hides it.

**Source issue:** https://github.com/lmorchard/agent-sessions/issues/23 — **Tier:** `auto-ok`
(every criterion reduces to a runnable check whose oracle exists; the touched paths
`driver/agent-session-driver.sh` and `driver/test-driver.sh` are both on `CLAUDE.md`'s drivable
allowlist; `driver/gate.py` and `skills/**` untouched; no auth, secrets, data
migration/deletion, deploy/infra/CI config or dependency change).

**Approach:** split the one matcher into two, per the spec's design decision. `fetch_open_prs`
starts requesting `closingIssuesReferences` — free, it is on the list query already made. A new
strict `pr_blocking_issue` consults that field and nothing else, and is used at the **selection
gate only**. The existing loose `pr_for_issue` is left byte-for-byte alone and keeps serving the two
**post-run discovery** call sites, which want the opposite error direction and whose behaviour the
frozen `driver/test-park-state.sh:89` fixture pins.

**Criteria:** C1 a mention-only PR must not block selection · C2 the query must actually request
`closingIssuesReferences`
[Full text + checks live in `checks.md`. Ids are assigned there and referenced here.]

**Line refs** are re-verified against `origin/main` @ `0b7aabf`; the issue's own refs had drifted.
See `checks.md` → "Line-reference drift".

---

## Phase 0: Freeze the acceptance checks — **DONE**

Written per `references/frozen-checks.md`. No implementation in this phase.

**Files:**
- Create: `docs/dev-sessions/2026-07-30-1816-23-selection-closing-refs/checks.md` — criteria +
  checks copied verbatim from the issue, ids assigned
- Modify: `driver/test-driver.sh` — the node `select: an open PR blocks an issue only when it
  closes it`, plus the `guard: body/branch matching still works where GitHub records no link` node.
  Authored by a subagent that was given the criteria and the harness patterns but **not** the
  implementation approach.

**Verification — automated:**
- [x] Every criterion's check runs and **fails for the expected reason** — `make driver-test`:
      C1(a), C1(b), C1(c), C2(a), C2(b) all FAIL; both liveness probes pass, so the failures are
      attributable to the matcher and the un-requested field, not to a broken stub. Verbatim
      output recorded in `checks.md`.
- [x] Every guard runs and **passes** — G1, G2 ok in the same run; G3 (`driver parses`) ok;
      G4: `make park-test` 21 passed / 0 failed, `make docs-check`, `make driver-check`,
      `make skill-readonly` all green at the freeze tree.
- [x] Freeze commit made; sha recorded in `checks.md` in a follow-up commit.

**Totals at freeze:** `74 passed, 5 failed`. The 5 are exactly C1(a,b,c) and C2(a,b).

---

## Phase 1: Split the matcher; gate selection on the closing link

One vertical slice — the query, the matcher, the call site and the operator-facing output all move
together. Splitting it further would leave an intermediate commit where the driver requests a field
nothing reads, or reads a field nothing requests.

**Advances:** C1, C2 — fully. Nothing remains for a later phase.

**Files:**
- Modify: `driver/agent-session-driver.sh` — three edits, described below.
- Test: none of my own. The frozen node in `driver/test-driver.sh` is the acceptance test and is
  **read-only from here on**; this slice adds no unit scaffolding, because the frozen node already
  exercises both directions end-to-end through the shipped driver.

**Key changes:**

1. `fetch_open_prs()` (`:332-335`) — add the field to the `--json` list. This is the whole of C2.

```bash
fetch_open_prs() {
  gh pr list --repo "$REPO" --state open --limit 200 \
     --json number,title,body,headRefName,url,closingIssuesReferences 2>/dev/null || echo '[]'
}
```

2. `pr_blocking_issue()` — new, immediately after `pr_for_issue` so the two read as a pair. Strict:
   the authoritative link and nothing else. Same `number<TAB>url` output shape as `pr_for_issue`,
   because the call site does `cut -f2` on it.

```bash
pr_blocking_issue() { # $1 = issue number, $2 = open-prs json
  printf '%s' "$2" | jq -r --arg n "$1" '
    .[] | select(
      [ (.closingIssuesReferences // [])[] | .number | tostring ] | index($n)
    ) | "\(.number)\t\(.url)"' | head -1
}
```

   `// []` matters: a PR served without the key (any stub that ignores the requested field list,
   including the frozen one) yields `null`, and `null[]` is a jq error, not an empty match.

3. `pr_for_issue()` (`:337-344`) — **unchanged**, byte for byte. Its comment gets the split
   written into it so the next reader does not "unify" the two back together. It keeps both
   discovery call sites, `:671` and `:795`.

4. The selection gate (`:433`, `:440`) — call the strict matcher, and say something when the two
   disagree rather than discarding the near-match silently (spec Open question 3, default: yes,
   one advisory line). Rendered as a `note:` under the ELIGIBLE line, mirroring the board-column
   advisory already at `:451-454`.

```bash
    prline="$(pr_blocking_issue "$n" "$prs")"
    mention=""
    [ -z "$prline" ] && mention="$(pr_for_issue "$n" "$prs")"
```

```bash
      if [ -n "$mention" ]; then
        say "                note: PR #$(printf '%s' "$mention" | cut -f1) names #$n but declares" \
            "no closing link -- not a gate"
      fi
```

   The advisory wording deliberately avoids the substring `already has an open PR`, which C1(b)
   greps for. That is a constraint the frozen check imposes on the implementation, which is the
   correct direction; it is recorded here so it does not read later as an accident.

**What this slice must NOT do** — each of these is a STOP, not a judgment call:
- Touch `driver/test-park-state.sh`. It is frozen and read-only.
- Touch `driver/gate.py`. Selection runs upstream of classification.
- Change `pr_for_issue`'s behaviour, or point the discovery call sites at the strict matcher.
  G1 is the tripwire; if it goes red, the decision was over-applied.
- Weaken, skip or reword any assertion in `driver/test-driver.sh`.
- Rename `pr_for_issue`. G1/G2 extract it **by name** out of the shipped driver, so a rename
  makes both guards report `not found (renamed?)`. Spec Open question 2's default named the loose
  function `pr_from_run`; adopting the split without the rename satisfies the default's actual
  content (two functions, opposite error directions) and keeps the guards runnable as written.
  Renaming would also be churn beyond the smallest reasonable change.

**Verification — automated:**
- [x] C1's check passes: `make driver-test` — `C1(a)`, `C1(b)`, `C1(c)` all `ok`
- [x] C2's check passes: `make driver-test` — `C2(a)`, `C2(b)` both `ok`
- [x] Guards still pass: `make driver-test` — `G1`, `G2`, `driver parses` all `ok`, suite
      `79 passed, 0 failed`; `make park-test` — 21 passed, 0 failed; `make check` — `all checks
      passed` (G4)
- [x] Tamper diff empty: `git diff c0a6500 --stat -- driver/test-driver.sh` — no output
- [x] The driver has exactly three matcher call sites, one strict at selection and two loose at
      discovery: `grep -n 'pr_for_issue\|pr_blocking_issue' driver/agent-session-driver.sh` →
      `:465` strict (selection), `:715` and `:839` loose (discovery), plus `:470`, the advisory's
      read of the loose matcher, which gates nothing

**Verification — manual:**
- [x] None required. Both criteria are machine-checkable; that is what makes this run `auto-ok`.
      No human-judgment criterion exists, so nothing is pending a human grade at the gate.

**Not covered by a frozen check — stated rather than glossed:** the advisory `note:` line (change
4, spec Open question 3's default) is *additive output* and no criterion constrains it. The frozen
node proves it does not break C1 — the advisory prints on exactly the C1 fixture and C1 stays green
— but nothing asserts that it prints, or what it says. Adding an assertion for it now would mean
editing a frozen check file, which is a STOP, so it stays uncovered and declared. Follow-up
candidate for `notes.md`, not something to smuggle past the freeze.

---

## Coverage check (plan self-review)

- **Every `Cn` appears in a phase's Advances:** C1 → Phase 1. C2 → Phase 1. ✔
- **Every phase advances at least one `Cn`:** Phase 0 is the freeze (exempt by the template);
  Phase 1 advances C1 and C2. ✔
- **Checks cited by command:** every automated checkbox names `make driver-test` plus the exact
  assertion labels to read, or a literal `git diff` / `grep` command. None says "tests pass". ✔
- **Placeholder scan:** no TBD, no "add appropriate error handling", no reference to a type or
  function no phase defines. `pr_blocking_issue` is defined in Phase 1 and used in Phase 1. ✔
- **Type consistency:** `pr_blocking_issue` emits `number<TAB>url`, the same shape `pr_for_issue`
  emits and the same shape the call site's `cut -f1` / `cut -f2` consume. One name, one shape,
  used consistently across the plan. ✔
