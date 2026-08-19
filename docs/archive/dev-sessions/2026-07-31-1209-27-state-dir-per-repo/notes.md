# Session notes — one state dir per repo, under XDG

**Issue:** https://github.com/lmorchard/agent-sessions/issues/27 · **Tier:** `auto-ok`
**Mode:** `agent-session express`, unattended, invoked by the board-driver
**Freeze:** `0ad6881` · **Branch:** `fix/27-state-dir-per-repo`

## What shipped

The state-directory default becomes one directory per repo under XDG:
`${XDG_STATE_HOME:-$HOME/.local/state}/agent-session/<owner>-<name>/`. Both defects the issue names
fall out of the layout — the orphan guard is per-repo because the marker it reads is, and
`--classify-only` is unambiguous because each repo has its own `runs/`. **No code anywhere compares
two repos**, which is what the issue asked for.

## The one decision the spec left open, and why the answer was forced

The spec said "`--state-dir` keeps working as an explicit override" without saying whether
`--state-dir X` then means *X* or *X/&lt;slug&gt;*. C3's fixture wording (`<state>/lmorchard-decafclaw/…`)
reads both ways, so this was a real load-bearing ambiguity, not a style question.

**Resolved as: `--state-dir X` means exactly X. Only the default moves.** Not chosen — forced.
`driver/test-park-state.sh` is issue #5's **frozen** check file, read-only, and at `:275-282` it
seeds a ledger at `$SEED_SD/runs.jsonl` and invokes `--state-dir "$SEED_SD"`, asserting the skip
reason cites the newer row. Under the `X/<slug>` reading the driver would look in
`$SEED_SD/stub-repo/`, fall back to "no local run record on this host", and flip two frozen
assertions — repairable only by editing another issue's oracle, which `frozen-checks.md` makes a
STOP. Checked before writing any code, which is the only reason it cost nothing.

**Verify-don't-assume earned its keep twice more here**, both times on things that would have
silently broken a file I could no longer edit:

- The startup report goes to **stderr via `log`**, not stdout via `say`. Several existing cases
  capture stdout *only* and match a bare four-digit issue number anywhere in it; a temp state-dir
  path is full of digits, so a stdout line widens a spurious-pass window.
- Resolution happens **after** the required-command loop, because the nest section asserts the
  *first line of stderr* from a bad `--skill-dir` run is that run's own error message. Emitting a
  state-dir line earlier makes it line one and flips that assertion.

Both were found by reading the frozen suite's negative assertions before writing, not by watching a
test fail.

## The probe finding worth generalising

`probe-01` and `probe-02` were written at plan step 4 to reproduce the issue's own reproduction —
which used **one explicit shared `--state-dir`**. After the fix they still reported "GAP PRESENT",
and the momentary temptation was to read that as a failure.

It is not. Two runs handed one explicit directory share one `inflight.json`, and the spec rejects
that design in as many words: *"keeping one shared directory with a repo-aware guard — that cannot
work, because a single `inflight.json` cannot represent two concurrent runs."* Real invocations pass
no `--state-dir` at all (neither `make run` nor `make run-self` does), so the default is what
carries the goal.

**The lesson: an intake-time reproduction can encode an incidental detail as if it were the
criterion.** The issue used `--state-dir` for *isolation* ("so it neither read nor wrote live
state"), and the probe inherited it as though it were part of the scenario. The frozen check, written
from the criterion rather than from the reproduction, used the right form. That is an argument for the
freeze procedure's separation of concerns rather than against it.

Both probes now run **both** forms, and form A is kept as a negative control: if the shared-directory
case ever stopped refusing, the fix would have bought C1 by making the orphan guard permissive.
Logged as clarification C-1 in `checks.md` — the verifier flagged, correctly, that this edits evidence
`checks.md` cites.

## Results

| | |
|---|---|
| C1 cross-repo start | pass — `make driver-test`, plus `probe-01` form B |
| C2 XDG per-repo default, reported | pass — `make driver-test`, plus `probe-03` (unmodified since freeze) |
| C3 `--classify-only` resolves per repo | pass — `make driver-test`, plus `probe-02` form B |
| G1 no assertion lost | pass — 112 passed, 0 failed (105/7 at freeze; the 97 pre-existing unchanged) |
| G2 no merge path | pass — `make driver-check` |
| G3 archive untouched | pass — `probe-04`, 100 files byte-identical, re-run after the migration |
| G4 `.gitignore` | pass — `.gitignore:6` |
| G5 project gate | pass — `make check` green |
| Tamper | **clean**, not clean-by-substitute — `git diff 0ad6881 -- driver/test-driver.sh` empty |

Independently verified by a subagent given only `checks.md` and the repo — not the plan, not the
commit rationale. It confirmed the criteria and CHECK text are byte-faithful to the issue (including
a codepoint audit for lookalike punctuation), found no coverage weakening, and could not discharge
one item directly: re-running the frozen suite against the pre-change driver, which the sandbox
denied. Teeth are established instead by `probe-03` — unmodified since freeze, and its verdict
inverted — and by the pre-change literal `STATE_DIR="./.driver-state"` making all three cases
unsatisfiable by construction.

## The migration, as run on this host

```
python3 docs/dev-sessions/2026-07-31-1209-27-state-dir-per-repo/migrate-ledger.py --apply
```

18 attributable rows → 8 (`lmorchard-agent-sessions`) + 10 (`lmorchard-decafclaw`), each re-read and
verified after writing. Reads the archive only. A second `--apply` skipped both ledgers rather than
duplicating. **Undo is `rm -rf` of the two new directories**; nothing was removed from
`./.driver-state/`, and G3 was re-verified afterwards.

Not driver code, deliberately: no criterion asks for migration logic, and a one-shot migration
living permanently in the driver is dead weight.

## What this change invalidated, and what was done about it

Per CLAUDE.md's "ask what it just invalidated" — these are claims *this session* falsified by doing
ordinary work, which no audit pass would have caught:

| Claim | Where | Action |
|---|---|---|
| "refuses a second run **against the same repo**" | `findings.md` | corrected, and now states the *mechanism* (layout, not comparison) — the issue's own fact 2 |
| same claim, operator-facing | `usage.md` | corrected the same way |
| per-run provenance lives in `.driver-state/runs.jsonl` | `design.md` ×2 | now cites the logged path; `./.driver-state/` named as the pre-#27 archive |
| "no `$HOME` assumptions" | driver file header | corrected — this change adds exactly one, deliberately |
| operator cannot find their runs | `usage.md` | new "Where the state directory is" section, incl. the cross-repo `jq` glob |

`docs/archive/` was left alone on purpose: it is labelled closed and describes what was true then.

## Residual risks, named rather than gated away

1. **An explicit shared `--state-dir` reintroduces both collisions**, by construction. That is the
   operator's choice and it is now documented in `usage.md`. Closing it would mean `--state-dir X`
   not meaning X, which #5's frozen oracle forbids.
2. **Issue #6's C1 check hardcodes `.driver-state/runs.jsonl`**, which this change turns into an
   archive that never gains a row. #6 is open and unstarted. **Not edited from this run** — see the
   PR body; `CLAUDE.md` draws the driver's write boundary at issue *metadata*, never issue *content*,
   and silently rewriting another issue's frozen check from inside an unattended run on a different
   issue is exactly the write that boundary exists to prevent. It needs one human edit.
3. **The spec's prose says "ten prior runs."** The archive actually holds 17 run directories and 18
   ledger rows (`probe-04` prints both). A stale count in the issue, not a defect in the work; G3
   protects whatever is there. Noted because it is this project's defect class 4 in miniature — a
   count stated away from its evidence.
