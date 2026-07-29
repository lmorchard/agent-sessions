# Park state as a GitHub label — Implementation Plan

**Goal:** Make the driver's park list correct and host-independent by moving the park record out of
`.driver-state/parked.jsonl` and onto the issue itself, as a `driver-parked` label.

**Source issue:** https://github.com/lmorchard/agent-sessions/issues/5 — **Tier:** `auto-ok`
(every criterion reduces to a fixture test against the shipped driver; work stays inside `driver/`
plus `Makefile` and `docs/`, touching neither `skills/**` nor `driver/gate.py`).

**Approach:** Decision D2 in the issue body. Selection already reads marker + tier, open PRs and the
board column from GitHub; the park list was its only local input, and it was both wrong (append-only
with no un-park record, so all three effective entries are stale) and per-machine (a gitignored file
relative to cwd). A label makes the park bit durable and repo-scoped by construction, and visible
where a human decides whether to `--retry`. `runs.jsonl` stays the local run *history* and still
supplies the skip line's reason — the ledger is history, the label is current state, and conflating
those two is the defect.

**Criteria:** C1 read side derives the park list from the label · C2 a parking outcome adds the
label, on both the normal and `--classify-only` paths · C3 a gate verdict removes it · C4 park state
survives an empty state dir, and `--retry` still overrides it.
Full text + checks live in `checks.md`; ids are assigned there.

**Verified `gh` behaviour this plan turns on** (probed 2026-07-29, both no-ops on state):

| Call | Result |
|---|---|
| `gh issue edit N --remove-label <label the issue lacks>` | **exit 0**, no error — so removal can be unconditional and quiet |
| `gh label create <existing label>` | **exit 1**, `already exists; use --force` — so creation needs `\|\| true` and suppressed output |

---

## Phase 0: Freeze the acceptance checks — DONE

Frozen at `4c46753`. `driver/test-park-state.sh` is **read-only from here on**.

**Verification — automated:**
- [x] Every criterion's check runs and fails for the expected reason — 13 failing assertions,
      recorded per criterion in `checks.md` under `AT FREEZE`
- [x] Every guard runs and passes — G1 (61 bash assertions + pytest), G2, G3, G4, G7
- [x] Harness sanity passes 7/7, which is what makes the failures attributable
- [x] Freeze commit made; sha recorded in `checks.md` in the follow-up commit

---

## Phase 1: The read side — the park list comes from the label

Selection stops consulting `parked.jsonl` and reads the park bit off the issue list it already
fetches. The skip line keeps citing a reason, taken from the latest ledger row when one is available
locally, with an explicit fallback when it isn't (a fresh host has the label but no history).

**Advances:** C1 fully; C4 partially — C4's `SKIP` and reason assertions land here, and its
`--retry` assertion is verified unbroken.

**Files:**
- Modify: `driver/agent-session-driver.sh` — `PARK_LABEL` constant; `parked_numbers()` rewritten to
  read the issues JSON on stdin; new `park_reason()`; `select_issues()` requests `labels` and pipes
  the JSON in.

**Key changes:**

```bash
# Park state lives on the issue, as a label. The old parked.jsonl was append-only
# with no un-park record, so every entry it produced was stale within one run, and
# being a gitignored path relative to cwd it never survived a host change either.
PARK_LABEL="driver-parked"

# Reads the issues JSON on stdin -- the same payload select_issues already fetched,
# so this costs no extra API call. Named `parked_numbers` deliberately: the frozen
# check extracts THIS function by name with sed, so a rename fails the check closed
# instead of silently grading a copy.
parked_numbers() { # issues json on stdin -> one parked issue number per line
  jq -r --arg label "$PARK_LABEL" \
     '.[]? | select((.labels // []) | any(.name == $label)) | .number' 2>/dev/null | sort -u
}

# The label carries no reason, so the reason comes from the run history -- which is
# what runs.jsonl was always for. Best effort by design: on a fresh host the label
# is present and the history is not, and saying so beats printing an empty reason.
park_reason() { # $1 = issue number -> the latest recorded reason for it
  local r=""
  if [ -s "$RUNS_LOG" ]; then
    r="$(jq -r --arg n "$1" --arg repo "$REPO" \
         'select(.issue == ($n|tonumber) and .repo == $repo) | .reason // empty' \
         "$RUNS_LOG" 2>/dev/null | tail -1)"
  fi
  if [ -n "$r" ]; then printf '%s\n' "$r"
  else printf '%s\n' "carries the $PARK_LABEL label; no local run record on this host"; fi
}
```

`select_issues()` changes in two places — `--json number,title,body,labels`, and
`parked="$(printf '%s' "$issues_json" | parked_numbers || true)"` — and the skip branch becomes
`reason="parked: $(park_reason "$n")"`.

**Verification — automated:**
- [ ] C1's check passes: `bash driver/test-park-state.sh` — section `C1` prints `7`
- [ ] C4's `SKIP    #7  parked` and `current reason` assertions pass
- [ ] Guards still pass: `make check`, `make driver-check`, `make skill-readonly`,
      `git diff origin/main..HEAD --stat -- skills/ driver/gate.py` empty

---

## Phase 2: The write side — one park routine, both paths

The parking case list is currently duplicated at `:563` (normal) and `:681` (`--classify-only`
recovery), and the recovery path is exactly how #656 got its stale record. Both become calls to one
`apply_park_state`, which appends the history line, writes the label, and — new — removes the label
on a gate verdict.

**Advances:** C2, C3.

**Files:**
- Modify: `driver/agent-session-driver.sh` — new `park_label_add()`, `park_label_remove()`,
  `apply_park_state()`; both duplicated `case` blocks replaced by one call each.

**Key changes:**

```bash
# The label is the state; parked.jsonl is still appended as HISTORY. Every line it
# holds was true when written -- "at time T, issue N was parked" -- and the bug was
# reading that history as current state. Nothing reads it for selection now.
apply_park_state() { # $1 = issue, $2 = outcome, $3 = ts, $4 = reason
  case "$2" in
    parked|failed|incomplete|no-gate)
      jq -n -c --arg issue "$1" --arg ts "$3" --arg outcome "$2" --arg reason "$4" \
        '{issue:($issue|tonumber), parked_at:$ts, outcome:$outcome, reason:$reason}' \
        >> "$PARKED_LOG"
      park_label_add "$1"
      say "  parked -- excluded from future selection unless --retry $1"
      ;;
    gate-eligible|gate-human)
      park_label_remove "$1"
      ;;
  esac
}
```

`budget-exhausted`, `driver-fault` and `ci-stale` fall through both arms untouched, which is G3 and
is deliberate: a config problem must not be hidden behind a skip reason, and a stale-CI verdict is
neither progress nor a park.

```bash
park_label_add() { # $1 = issue number
  # The label must exist before it can be applied, and `gh label create` exits 1
  # when it already does (verified) -- hence the discard. Never fatal: losing the
  # recorded outcome over a label write would be worse. But never silent either,
  # because a failed add silently un-parks the issue.
  gh label create "$PARK_LABEL" --repo "$REPO" --color FBCA04 \
     --description "the agent-session driver parked this issue" >/dev/null 2>&1 || true
  gh issue edit "$1" --repo "$REPO" --add-label "$PARK_LABEL" >/dev/null 2>&1 \
    || say "  WARNING: could not add the $PARK_LABEL label to #$1 -- it stays selectable"
}

# Unconditional, because `--remove-label` on an issue that lacks the label exits 0
# without error (verified). Reading the labels first to avoid a no-op would cost an
# API call to prevent nothing.
park_label_remove() { # $1 = issue number
  gh issue edit "$1" --repo "$REPO" --remove-label "$PARK_LABEL" >/dev/null 2>&1 \
    || say "  WARNING: could not remove the $PARK_LABEL label from #$1 -- it stays parked"
}
```

**Verification — automated:**
- [ ] C2's check passes: `bash driver/test-park-state.sh` — section `C2`, both paths log
      `--add-label driver-parked` for `issue edit 7`
- [ ] C3's check passes: section `C3`, both verdicts log `--remove-label` and never `--add-label`
- [ ] C4's `--retry` assertion still passes
- [ ] Guards still pass, G3 included: `driver/test-driver.sh`'s
      `budget-exhausted is excluded from the park list` assertion still finds the case list

---

## Phase 3: Wire the frozen checks into `make check`, and update the docs

The frozen file was deliberately left out of `make check` at freeze, because G1 is "`make check`
green" and a failing check file would have broken that guard before any work started. Now it passes,
so it joins the suite and G1 covers it permanently.

**Advances:** no criterion — and that is correct rather than scope creep. It converts C1–C4 from a
file someone has to remember to run into part of the standing gate, which is a property of the
*repo*, not of the criteria. (`plan.md:84`'s "every phase advances at least one `Cn`" flags this the
same way it flags Phase 0; noted in `docs/design.md` as an agreed wording nit.)

**Files:**
- Modify: `Makefile` — `park-test` target; added to `check`; `help` line.
- Modify: `docs/design.md` — roadmap item 6 (`parked.jsonl` lies) closed; item 4 loses its park
  half, keeping the GHA host.
- Modify: `docs/findings.md` — the two verified `gh` label facts.
- Write: `{session-dir}/notes.md` — session summary.

**Verification — automated:**
- [ ] `make check` runs the new file and is green — the full suite, including `park-test`
- [ ] G7 still empty: `git diff origin/main..HEAD --stat -- skills/ driver/gate.py`
- [ ] Tamper check: `git diff 4c46753 -- driver/test-park-state.sh` is **empty**

**Verification — manual:**
- [ ] `make dry-run-self` against the real board still reads the queue and reports sensibly with
      no park labels anywhere yet — the one path a stub cannot vouch for
