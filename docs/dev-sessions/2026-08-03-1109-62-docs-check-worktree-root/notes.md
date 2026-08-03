# Notes — #62 `docs-check` scans zero files inside a worktree

Unattended `express` run, tier `auto-ok`, 2026-08-03. Branch `fix/62-docs-check-worktree-root`
off `origin/main` at `7fd6cdd`.

## What was wrong, and what shipped

Two defects, one mechanism: `md_files()` decided what to exclude by matching **directory names**
against the **absolute** path.

| | Defect | Fix |
|---|---|---|
| C1 | Matching absolutely let a directory exclude *itself*. From `.worktrees/<branch>/`, ROOT's own path carries `.worktrees`, so every file beneath it matched → **0 files scanned, exit 0** | match `p.relative_to(ROOT).parts` |
| C2 | No name list can be right. `.worktrees/` is the fallback this repo never uses; Claude Code creates worktrees at `.claude/worktrees/` → a second checkout's docs scanned as this one's | `under_nested_worktree()` — skip any descendant carrying a `.git` entry, ROOT exempt |

`SKIP_DIRS` keeps every entry it had. The two rules are not redundant: the name list catches a
bare `.worktrees/` holding no checkout (G1's case), the marker catches a real worktree at a path
no list mentions.

Measured, same commit, two working directories:

| | at freeze | after |
|---|---|---|
| worktree root | 0 files, exit 0 | 116 files, exit 0 |
| main checkout | 226 files, **11 failures** | 113 files, 0 failures |

The 11 were all session artifacts under `.claude/worktrees/docs+orientation-repo-detail/docs/dev-sessions/`,
frozen-exempt in their real location and stripped of the exemption by the copied prefix. All 82
session records are exempt again. `is_frozen()` was never touched — the exemption damage was a
*consequence* of over-scanning, which is worth saying because "frozen records lost their
exemption" reads like an `is_frozen()` bug and is not one.

## The check-reviewer earned its keep

It greened the **entire manifest** twice without doing the work, and ran both simulations rather
than asserting them:

- **SIM B** — keep the absolute match, but disable exclusions wholesale when `ROOT` is tainted.
  19 passed, exit 0. Actively harmful in this issue's own environment: from any worktree,
  `node_modules`, `.venv`, `.git` and nested worktrees all become scannable. **G1 could not catch
  it, because G1 only ever ran with an untainted `ROOT`** — the one configuration where the taint
  branch is never taken.
- **SIM A** — `SKIP_DIRS |= {".claude"}`. 19 passed, exit 0, *and* it greened G3's original
  wording on main, since all 11 real failures lived under `.claude/`. The old C2 control could
  not see it, being neither hidden nor named `.claude`.

Both closed pre-freeze (so no amendment, no tier cost) by two assertions: excluded descendants
*inside* C1's tainted `ROOT` (right answer 2, wrong answer 4), and a second worktree at the
unremarkable `tools/checkout-b/` plus a hidden non-worktree `.github/CONTRIBUTING.md` in the
control that must still be scanned. Together those admit only marker-based logic.

**The lesson worth keeping is about where the review sat**, not about these two holes. The freeze
window is the only point where strengthening a check is free; after the freeze commit the same
fix costs an amendment and the tier. Both of these were found by a context that had not read the
plan, in one pass, on checks that looked fine to the author and to me.

## Two guards failed at freeze, and neither was waived

- **G2** — its recorded baseline (113/113) was measured *before* the freeze tests existed, and it
  concealed a third red test: `test_gate_test_wiring.py::test_new_test_file_runs_under_gate_test_with_no_makefile_edit`,
  which shells out to `make gate-test` and asserts `returncode == 0`. That inner run was red
  *because C1/C2 were red by design*. **A structural artifact worth naming: freezing failing
  checks in a repo whose own meta-test asserts its suite is green will always produce this.** It
  self-resolved at 120/120/0 with no edit to that file — and the file was added to the read-only
  list at freeze precisely so "it cleared" is distinguishable from "someone helped it".
- **G3** — had **no configuration in which it genuinely passed** at freeze: red on main for C2's
  reason, green in the worktree for C1's, i.e. green *because* the bug was present. Its
  "non-zero file count" was also unobservable, since `main()` prints no count. Strengthened
  pre-freeze in the strict direction only — both trees, count printed, floor asserted.

That second one is the sharper instance of this project's own defect class 2. **A guard that
passes for the reason the criterion is broken is worse than a guard that fails**, and only asking
"which tree, and what does the command actually print?" surfaced it.

## Residual the tests cannot close

An implementer willing to hardcode the *fixture's own path names* (`"checkout-b" in p.parts`)
greens C2 with no marker logic. No fixture closes this in principle — it can plant only finitely
many spellings. **Review item, not a test item:** confirm the diff mentions none of
`checkout-b`, `.claude`, `.github`. It does not.

Everything *mechanism*-shaped dies against the strengthened set: `docs/**` allowlisting, depth
rules, dot-prefix rules, name additions, taint-disables-exclusions, taint-drops-the-name, and
`[x for x in p.parts if x not in ROOT.parts]`. The two survivors are the two intended.

## Out of scope, recorded rather than fixed

- **`.pytest_cache` is not in `SKIP_DIRS`**, so `.pytest_cache/README.md` is scanned. Noticed
  while grounding G3's count floor — which is why G3 asserts a floor and not an equality. Not
  fixed here: it is not in the spec, and the smallest-change rule applies. Worth a one-line
  follow-up.
- **`assertion_lint` and `commit_lint` were not audited** for the same `__file__`-derived shape.
  The spec's "What we're NOT doing" is explicit that this is a separate issue with separate
  checks — a single deliberate pass, not a third one-at-a-time discovery. **This is the fourth
  detector-level defect in this project's history**, so the pass is worth filing.
- `under_nested_worktree()` stats `<dir>/.git` per directory per file with no memoisation.
  Negligible at ~116 files; noted so nobody mistakes it for an oversight.

## The point of the issue, stated as a result

`docs-check` is in `make check`, and `make check` is the `project-gates` row of every merge gate
this project publishes. Every express run works in a worktree. So on **every run to date**,
`project-gates: make check green` included a doc-rot detector that examined nothing — and the one
place a run's *own* freshly-written session docs would be checked was the one place it was blind.

This run's `make check` is the first whose `docs-check` scanned anything (116 files), and these
session notes are among the files it scanned. Link and table checks now cover session docs;
freshness remains exempt by design, `docs/dev-sessions/` being a historical record.

Found by the unattended run on #51, reported as *"my green baseline for that target meant
nothing"* — a run catching a defect in the infrastructure grading it. Fixed by another unattended
run whose own baseline was the same null, which is a decent argument that the loop is working.
