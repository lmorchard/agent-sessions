# Exempt `--dry-run` from the live-orphan refusal — Implementation Plan

**Goal:** let `--dry-run` report a live orphan without refusing to run, so the before/after
eligible-count measurement stays available while a run is in flight.

**Source issue:** https://github.com/lmorchard/agent-sessions/issues/51 — **Tier:** `auto-ok`
(C1 reduces to an exit status plus two output assertions in an existing bash fixture harness;
the work lands in `driver/agent-session-driver.sh` and `driver/test-park-state.sh`, both on
CLAUDE.md's drivable allowlist, and not in `driver/gate.py`.)

**Approach:** the property that justifies the exemption is *"this invocation cannot spend or
mutate"*, not *"a run is in progress"*. `--dry-run` makes no `claude` invocation, writes nothing
to the state dir, and creates no worktree, so the refusal protects nothing there. Keep printing
the warning — that half is useful, and suppressing it would hide a genuinely dead run from the
command an operator is most likely to reach for. Do **not** exempt `--classify-only`: it derives
an outcome from a run's live state, and a live run's state is still moving.

**Criteria:** C1 — with a live-orphan marker in the state dir, `--dry-run` prints the orphan
warning, completes selection, and exits 0.
(Full text + checks live in `checks.md`. Ids are assigned there and referenced here.)

---

## Phase 0: Freeze the acceptance checks — DONE

Written per `references/frozen-checks.md`. No implementation in this phase.

**Files:**
- Created: `docs/dev-sessions/2026-08-01-1507-51-dry-run-orphan-exempt/checks.md`
- Created: `docs/dev-sessions/2026-08-01-1507-51-dry-run-orphan-exempt/g3-baseline-labels.txt`
- Modified: `driver/test-park-state.sh` — the `#51` section the checks name

**Verification — automated:**
- [x] C1's check runs and **fails for the expected reason** — exit `2` from `die` on the line
      after the `ORPHAN STILL RUNNING` message; selection never reached. Recorded verbatim in
      `checks.md`. Not an import error, unbound variable, missing fixture or stub typo.
- [x] The attributability control **passes** — same fixture, `child.pid` removed, exit `0`.
- [x] C1 assertion 3's needle verified reachable under the stock stub fixture before freezing.
- [x] Guards G1/G2/G3 run and **pass** — `33 passed, 2 failed`, the two failures being C1's, and
      all 28 baseline labels still `ok`.
- [x] Freeze commit made: `fa4ca83`; sha recorded in `checks.md`.

---

## Phase 1: Exempt `--dry-run` from the refusal

Change the startup orphan check so a live orphan still produces the full warning, but the
`die` is reached only for invocations that can spend or mutate. One vertical slice: this is the
whole behaviour change, and the frozen checks grade it end-to-end through the shipped driver.

**Advances:** C1 (fully). Nothing remains for a later phase.

**Files:**
- Modify: `driver/agent-session-driver.sh` — the startup orphan block at `:1037–1052`
- Test: none added. The frozen acceptance tests in `driver/test-park-state.sh` already cover
  this end-to-end and are **read-only from here on**. A slice unit test would be a second copy
  of the frozen one, which is the replica this suite's header forbids.

**Key changes:**

Today the live-orphan branch always ends in `die`, and the "recover it with" line below it is
reached only when the orphan is *not* live:

```bash
  if [ -n "$_ipid" ] && kill -0 "$_ipid" 2>/dev/null; then
    say "  ORPHAN STILL RUNNING (pid $_ipid, reparented) -- it is unsupervised and still spending."
    say "  Let it finish, then:  --classify-only $(jq -r '.issue' "$STATE_DIR/inflight.json" 2>/dev/null)"
    say "  Or kill it:           kill -TERM $_ipid"
    die "refusing to start a second run while an orphan is live"
  fi
  say "  recover it with:  --classify-only $(jq -r '.issue' "$STATE_DIR/inflight.json" 2>/dev/null)"
  say ""
```

Becomes an explicit if/else, so falling through the live branch cannot also print the
not-live advice:

```bash
  if [ -n "$_ipid" ] && kill -0 "$_ipid" 2>/dev/null; then
    say "  ORPHAN STILL RUNNING (pid $_ipid, reparented) -- it is unsupervised and still spending."
    say "  Let it finish, then:  --classify-only $(jq -r '.issue' "$STATE_DIR/inflight.json" 2>/dev/null)"
    say "  Or kill it:           kill -TERM $_ipid"
    # The refusal exists because two concurrent runs cannot share one inflight.json
    # and because the orphan is still spending. The property that matters is
    # "THIS invocation can spend or mutate", not "a run is in progress" --
    # --dry-run invokes no claude, writes nothing to the state dir and creates no
    # worktree, so refusing it protects nothing and costs the operator the one
    # measurement they reach for while a run is live. The warning above still
    # prints: suppressing it would hide a genuinely dead run.
    #
    # NOT --classify-only, deliberately. That path derives an outcome from a run's
    # live state and writes a ledger row plus park labels, and a live run's state
    # is still moving -- the advice two lines up is to wait, not a door to open
    # early. See issue 51's design decisions.
    if [ "$DRY_RUN" -eq 0 ]; then
      die "refusing to start a second run while an orphan is live"
    fi
    say ""
  else
    say "  recover it with:  --classify-only $(jq -r '.issue' "$STATE_DIR/inflight.json" 2>/dev/null)"
    say ""
  fi
```

The `else` branch is not a behaviour change — it is the same two lines, moved inside an `else`
so they stay unreachable when the orphan is live. Under the old shape `die` guaranteed that;
once `--dry-run` can fall through, an explicit `else` is what preserves it. Printing
"recover it with: `--classify-only 99`" directly beneath "ORPHAN STILL RUNNING" would advise
exactly the action G2 exists to prevent.

`DRY_RUN` is initialised to `0` at `:69` and set to `1` by `--dry-run` at `:143`, so it is always
bound under `set -u` by the time this block runs (`:1037`), which is after argument parsing.

**Verification — automated:**
- [ ] C1's check passes: `make park-test` — the four `#51 C1` assertions all `ok`
- [ ] Guard G1 passes: `make park-test` — `a real run still refuses while the orphan is live`
      and `  and never invokes claude` both `ok`
- [ ] Guard G2 passes: `make park-test` — `--classify-only still refuses while the orphan is
      live` is `ok`
- [ ] Guard G3 passes: `make park-test 2>&1 | grep -E '^  ok '` contains every line of
      `g3-baseline-labels.txt`
- [ ] `make check` passes (the project's own gate; `park-test` is one of its targets)
- [ ] Tamper diff empty: `git diff fa4ca83 -- driver/test-park-state.sh`

**Verification — manual:**
- None. C1 has no human-judgment component and the tier is `auto-ok`.

---

## Out of scope — noted, not fixed

Recorded here per `execute.md` step 5 rather than fixed in this run:

- **`make docs-check` is vacuous inside a worktree.** `scripts/docs_check.py:44` lists
  `.worktrees` in `SKIP_DIRS` and `md_files()` filters on absolute-path parts, so every run
  executed from `.worktrees/<branch>/` scans zero markdown files and reports green regardless.
  That is every express run. Unrelated to #51; file it as its own issue.
- **Changing how a live orphan is detected** — the issue's own "What we're NOT doing".
- **Making the refusal configurable** — likewise.
