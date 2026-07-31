# Plan — one state dir per repo, under XDG

**Issue:** https://github.com/lmorchard/agent-sessions/issues/27
**Tier:** `auto-ok` (body heading, authoritative; the label agrees)
**Frozen at:** `0ad6881` — `checks.md` lists `driver/test-driver.sh` as the only check file,
read-only from Phase 1 onward.

## Phase 0 — freeze (DONE, before any implementation)

- [x] `checks.md` written, criteria and CHECK text verbatim from the issue
- [x] Frozen cases authored by a check-author subagent given the criteria but no implementation
      approach; appended to `driver/test-driver.sh` (288 insertions, 0 deletions)
- [x] Each criterion case observed failing for the right reason — `make driver-test`:
      `105 passed, 7 failed`, all 7 failures `#27` criterion cases
- [x] Guards run and observed **passing** at freeze: G1 `make driver-test` (97 pre-existing
      assertions, unchanged), G2 `make driver-check`, G3 `probe-04-g3-fingerprint.py --write`
      (100 files, 17 run dirs, 18 ledger rows), G4 `.gitignore:6`, G5 `make check`
- [x] Freeze commit `0ad6881`; sha recorded in the follow-up commit `4627fee`

## Phase 1 — the default resolves per repo, under XDG, and says where

**Advances:** C1, C2, C3 — all three, from one change. That is the spec's central claim: *"No
repo-comparison code is added anywhere."* The orphan guard becomes per-repo because the marker it
reads is, and `--classify-only` stops being ambiguous because each repo has its own `runs/`. If
this phase finds itself comparing repos, the layout change did not land.

**Files:** `driver/agent-session-driver.sh` only.

### The change

1. `STATE_DIR="./.driver-state"` becomes `STATE_DIR=""` — empty means "not given".
2. Where `STATE_DIR` is made absolute, default it first when empty:
   `${XDG_STATE_HOME:-$HOME/.local/state}/agent-session/<owner>-<name>`, slug flat with `-`
   (the spec's stated default for that open question).
3. Die with a clear message if neither `XDG_STATE_HOME` nor `HOME` is set and no `--state-dir`
   was given — otherwise the failure surfaces as an obscure `mkdir` error under `set -e`.
4. Report the resolved path once, at startup.
5. Update the `--state-dir` line in `usage()` to describe the new default.
6. Update the file header's *"no `$HOME` assumptions"* claim, which this change falsifies.

### Two placement constraints, both load-bearing

Neither is stylistic; each is a frozen or pre-existing assertion that would break.

- **The report goes through `log` (stderr), not `say` (stdout).** Several existing cases capture
  **stdout only** and assert on digits in it — `test-driver.sh`'s mixed-queue case (a) matches a
  four-digit issue number anywhere in stdout, and a temp state-dir path is full of digits. Adding a
  stdout line there widens a spurious-pass window in an assertion I cannot edit, because
  `test-driver.sh` is frozen from Phase 1. `log` also matches the spec's own wording ("one log
  line") and the file's convention: `say` is the report, `log` is diagnostics.
- **It must come *after* the required-command loop, not at the flag defaults.** The nest section's
  control probe asserts the **first line of stderr** is `error: --skill-dir does not exist: /nope`
  (`test-driver.sh:587-588`). A state-dir line emitted before that `die` becomes the first line and
  flips it. Resolving at the existing `STATE_DIR="$(abspath "$STATE_DIR")"` site satisfies this:
  it sits after skill-dir validation and after `for c in gh jq git`.
- **`mkdir -p "$STATE_DIR/runs"` stays where it is**, after validation, or the nest cases'
  `and does not create the state dir` → `absent` assertions flip.

### Verification

- [ ] `make driver-test` — the three C-cases flip to pass, G1/G2 `#27` cases stay passing, and all
      97 pre-existing assertions still pass
- [ ] `python3 docs/dev-sessions/2026-07-31-1209-27-state-dir-per-repo/probe-01-orphan-crossrepo.py`
      — re-run C1's original demonstration; expect `VERDICT: no gap`
- [ ] `python3 .../probe-02-classify-only-ambiguous.py` — expect `VERDICT: no gap`
- [ ] `python3 .../probe-03-c2-default-state-dir.py` — expect `VERDICT: C2 SATISFIED`
- [ ] `make check` — green (G5)
- [ ] `bash -n driver/agent-session-driver.sh` — covered by the suite's own syntax case

## Phase 2 — correct the `findings.md` claim this change makes true

**Advances:** no criterion. Spec-mandated rather than scope creep, and named as such rather than
given an invented criterion: the issue's Open Questions settle it — *"Does `findings.md:547`'s
wording get corrected in this PR or separately? **Default:** in this PR."* It is also the issue's
own current-state fact 2.

**Files:** `docs/findings.md`.

The line (now at `:595`, not `:547` — an intake-time snapshot) reads *"Startup now detects a live
orphan and refuses to start a second run against the same repo."* Today that is false in the
over-narrow direction: the code refuses regardless of repo. After Phase 1 the sentence becomes
true — but it still reads as though the guard *compares* repos, which it does not and must not.
So the edit makes the mechanism legible: the scoping is structural, a consequence of one state
directory per repo, not a comparison.

### Verification

- [ ] `make docs-check` — green (no dead links, no split tables, no stale counts)
- [ ] The edited clause states the mechanism, and asserts no count

## Phase 3 — migrate the existing ledger non-destructively

**Advances:** no criterion; guarded by **G3**. Mandated by the spec's second design decision:
*"Split the existing `runs.jsonl` rows by their `repo` field into the two new per-repo ledgers, and
leave `./.driver-state/` in place as an archive."*

**Files:** none that ship. This is a **one-time host-local operation**, not driver code — no
criterion asks for migration logic, and a one-shot migration living permanently in the driver is
dead weight. It runs from a script kept in the session directory as a re-runnable, auditable
artifact, and the exact invocation and output go in `notes.md` so a human can review or undo it
(undo = delete the new directory; nothing is removed from the archive).

Idempotent by construction: it refuses to write a per-repo ledger that already has rows, so a
second run reports and skips rather than duplicating.

### Verification

- [ ] `python3 .../probe-04-g3-fingerprint.py` — `G3 PASS`, every fingerprinted file under
      `./.driver-state/` byte-identical
- [ ] Row counts: per-repo ledgers sum to the archive's pre-existing row count
- [ ] `.driver-state/` still present in `.gitignore` (G4)

## Traceability

| Phase | Advances | Guards touched |
|---|---|---|
| 0 freeze | — (authors the oracle) | G1, G2, G3, G4, G5 all run and passing |
| 1 per-repo default + report | C1, C2, C3 | G1, G2, G5 |
| 2 `findings.md` clause | none — spec-mandated (Open Questions) | G5 (`docs-check`) |
| 3 ledger migration | none — spec-mandated (Design decisions) | G3, G4 |

Every `Cn` in `checks.md` appears in Phase 1. Phases 2 and 3 advance no criterion; both are
explicitly required by the spec, and the plan self-review's "scope creep or a missing criterion"
resolves as *neither* — they are non-criterion work the spec names, so they are recorded here
rather than smuggled in or given a criterion they don't have.

## What this plan deliberately does not do

- **No repo-comparison in the orphan guard.** The layout makes it unnecessary; adding it would
  mean the layout change failed.
- **No change to `--state-dir`'s meaning.** `--state-dir X` is still exactly X. See `checks.md`
  for why this is forced rather than chosen: `driver/test-park-state.sh` is another issue's frozen
  oracle and depends on it.
- **No migration code in the driver, and no `scripts/` addition.** No criterion asks for it.
- **No move or deletion of `./.driver-state/`.** G3.
- **No removal of `.driver-state/` from `.gitignore`.** G4 — it becomes vestigial, and removing it
  would re-open the `git add -A` window that has bitten this project twice.
- **No update to issue #6's C1 check** as part of the code change. Handled at the PR, see below.

## The open question that lands in the PR body, not the code

The issue's first Open Question: **#6's C1 check hardcodes `.driver-state/runs.jsonl`**, which
this change turns into a frozen archive that never gains a row. #6 is still open and unstarted (no
branch, no PR — verified). Its stated default is *"land this one after #6, or update #6's check to
the per-repo path as part of this work and say so in the PR."*

This run takes the second option only as far as it honestly can: **#6's check is stale as of this
PR, and the PR body says so explicitly**, naming the replacement path. Editing issue #6's body is
deliberately left to the human at the merge gate rather than done unattended — `CLAUDE.md` draws
the driver's write boundary at issue *metadata*, never issue *content*, and this issue's own tier
reasoning asserts "It writes no issue or PR content." Silently editing another issue's frozen
check from inside an unattended run on a different issue is the kind of write that boundary exists
to prevent. Flagging it costs the human one edit and keeps the boundary intact.
