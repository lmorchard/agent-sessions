# Frozen acceptance checks

**Source:** https://github.com/lmorchard/agent-sessions/issues/62
**Frozen at:** `2d7c4a6` (2026-08-03) — the tamper-diff baseline.

**Check files — read-only from Phase 1 onward:**
- `scripts/test_docs_check.py`
- `scripts/test_gate_test_wiring.py` — **added at freeze step 4 on the reviewer's finding**, not
  because this work touches it, but because it is *red at freeze* (see G2) and its failing
  assertion is literally `make gate-test` returncode `== 0`. A red test file outside the declared
  tamper surface, whose message points at an exit-status assertion, is an invitation. It is issue
  #50's frozen check file and this run must not edit it; its whole-file diff against the freeze
  sha must be empty.

**This run is an instance of "when the work must edit its own oracle"** — the file under change
(`scripts/docs_check.py`) is the module the frozen check imports. But the check *files* are disjoint
from the implementation file, so the ordinary whole-file tamper diff applies to both paths above and
is meaningful. Stated so a reader does not reach for the substitute procedure unnecessarily.

## C1

CRITERION: GIVEN a `ROOT` whose own path contains a component named in `SKIP_DIRS`, WHEN
`docs_check` enumerates markdown files, THEN it SHALL still find the files beneath that `ROOT`.

CHECK: a new case in `scripts/test_docs_check.py` that sets `ROOT` to
`<tmp>/.worktrees/<branch>`, writes two markdown files beneath it, and asserts both are scanned;
with a control at `<tmp>/plain/<branch>` asserting the same two.

Constraint carried from the spec, because it is what made the bug survivable: the `isolate`
fixture does `monkeypatch.setattr(docs_check, "ROOT", tmp_path)`, and `tmp_path` never contains
an excluded component — so every existing test bypasses the path-matching this bug lives in.
C1's case must therefore **not** use `isolate` as-is.

Realised as `test_c1_root_under_an_excluded_directory_name_still_scans_its_files` +
`test_c1_control_root_under_a_plain_directory_name_scans_its_files`. `isolate` is left untouched;
the tainted `ROOT` is layered over it through the same function-scoped `monkeypatch`, so it is
restored automatically.

AT FREEZE: **fails** — `AssertionError: assert [] == ['README.md', 'docs/design.md']`. Zero files
enumerated, which is the defect and not a setup error; the control builds the identical tree via
the same helper and finds both. 19 collected in the file, so the case ran.

## C2

CRITERION: GIVEN a *sibling* git worktree beneath `ROOT` at a path `SKIP_DIRS` does not name —
Claude Code creates them at `.claude/worktrees/<branch>/`, **no dot on `worktrees`** — WHEN
`docs_check` enumerates markdown files, THEN it SHALL NOT scan any file inside that worktree.

CHECK: a new case in `scripts/test_docs_check.py` that builds, beneath `ROOT`, a directory
containing a `.git` file whose content is `gitdir: …` plus a markdown file under it, and asserts
that file is not scanned; with a control asserting a markdown file at the same depth under a plain
(non-worktree) directory *is* scanned.

Realised as `test_c2_a_nested_git_worktree_is_not_scanned` +
`test_c2_control_a_plain_nested_directory_at_the_same_depth_is_scanned`.

AT FREEZE: **fails** — `AssertionError: assert ['.claude/worktrees/fix-62/docs/design.md',
'docs/design.md', 'tools/checkout-b/docs/design.md'] == ['docs/design.md']`. Both planted worktrees
were scanned; expected neither.

## Guards

(Pass today; must keep passing. Not criteria — they can't fail at freeze. **G2 and G3 are the
exceptions and both fail at freeze**; each says why, and neither is waived.)

- **G1.** Exclusion still works for *descendants*: a `.worktrees/` directory **inside** `ROOT` is
  still skipped. CHECK: a case with `ROOT = <tmp>` and a file at `<tmp>/.worktrees/x.md` asserting
  it is not scanned.
  **This is the guard that blocks the obvious wrong fix** — deleting `.worktrees` from `SKIP_DIRS`
  would green C1 and reintroduce scanning one branch's docs while linting another's.
  Realised as `test_g1_an_excluded_directory_inside_root_is_still_skipped`, which also plants
  `node_modules/pkg/README.md` so a fix that special-cases `.worktrees` alone while breaking the
  general descendant rule is caught.
  AT FREEZE: **passes** — the shipped `md_files()` returned exactly `['docs/design.md']`, not an
  empty set; it passes for the stated reason rather than a vacuous one.

- **G2.** All existing `docs_check` cases pass unchanged. CHECK: `make gate-test`, no case lost,
  newly skipped or newly failing.
  AT FREEZE: **FAILS**, and the true baseline is recorded here rather than the pre-freeze one.
  `uv run pytest driver/test_*.py scripts/test_*.py` (verbatim what `make gate-test` runs) →
  **120 collected, 117 passed, 3 failed, 0 skipped**. The three:
  1. `test_docs_check.py::test_c1_root_under_an_excluded_directory_name_still_scans_its_files` — C1, red by design.
  2. `test_docs_check.py::test_c2_a_nested_git_worktree_is_not_scanned` — C2, red by design.
  3. `test_gate_test_wiring.py::test_new_test_file_runs_under_gate_test_with_no_makefile_edit` —
     **collateral, not a pre-existing break.** It shells out to `make gate-test` and asserts
     `without_probe.returncode == 0` (`:289`); that inner run is red precisely because C1/C2 are
     red. It self-resolves when the fix lands. Verified by reading the assertion and its output,
     not inferred.
  **The pre-freeze figure was 113 collected / 113 passed** — measured before the seven new cases
  existed. That is what "existing cases pass unchanged" is measured against; G2 is discharged at
  the gate by 120/120/0, and a grader can tell "the collateral cleared" from "someone edited it"
  because both check files are in the read-only list above.

- **G3.** `python3 scripts/docs_check.py` from the repo root still reports the same verdict on the
  real tree. CHECK: exit 0 and a non-zero file count.
  AT FREEZE: **FAILS in both trees, for two different reasons** — which is what the reviewer
  found, and it is why the check is stated more precisely below rather than taken at face value.
  - From the **main checkout**: exit 1, `docs-check: 11 problem(s)`, 226 files scanned. This is
    C2's own symptom, predicted by the spec in those words: *"`make check` therefore cannot go
    green on this repo while any `.claude/worktrees/` copy exists."* All 11 are session artifacts
    under `.claude/worktrees/docs+orientation-repo-detail/docs/dev-sessions/`, frozen-exempt in
    their real location and stripped of the exemption by the copied path prefix.
  - From the **worktree** the work happens in: exit 0 — but `len(md_files()) == 0` against 115
    markdown files on disk. That is C1 live, presenting as a pass. **So G3 as literally worded has
    no configuration in which it genuinely passes today**, and its "non-zero file count" is not
    observable from the command it names, because `main()` prints no count.
  **Strengthened at freeze step 4, in the strict direction only** (recorded so the direction is
  checkable, not asserted): the original wording is kept verbatim above; it is discharged at the
  gate by requiring **both** trees to satisfy **both** clauses, with the count made observable —
  - `python3 scripts/docs_check.py` exits 0, **and**
  - `python3 -c "import sys;sys.path.insert(0,'scripts');import docs_check;print(len(docs_check.md_files()))"`
    prints **≥ 100**,
  - from the worktree root **and** from the main checkout with its `.claude/worktrees/` copy still
    in place.
  A floor, not an equality: the real count is environment-dependent (`.pytest_cache/README.md` is
  scanned and `.pytest_cache` is not in `SKIP_DIRS`). Today's on-disk figures are 115 in the
  worktree, 112 tracked. Deleting the `.claude/worktrees/` copy would green the original wording
  with no fix at all; naming both trees is what closes that.

- **G4.** `ROOT` itself does not exclude itself via its own `.git`. A main checkout has `.git` as a
  *directory* and a worktree has it as a *file*; either way `ROOT` carries one, so a rule that skips
  "any directory containing a `.git` entry" applied to `ROOT` would scan zero files — reintroducing
  the C1 bug through the C2 fix. CHECK: the C1 cases still pass with a `.git` entry created at
  `ROOT`, from both the excluded-name and plain spellings.
  **This is the guard that blocks the obvious wrong fix for C2**, and it is C1's principle restated
  against the new mechanism: a directory must not be able to exclude itself.
  Realised as two tests, because the guard's two spellings have different force:
  - `test_g4_a_dot_git_entry_at_root_does_not_exclude_root` — the *plain* spelling, asserted
    absolutely on both `.git`-as-directory and `.git`-as-file. **Real teeth today:** "skip any
    directory containing a `.git` dir" fails arm 1, "…a `.git` file" fails arm 2; only exempting
    `ROOT` itself passes both.
  - `test_g4_a_dot_git_entry_at_root_changes_nothing_under_an_excluded_name` — the *excluded-name*
    spelling, stated as an **invariance** (`.git` at `ROOT` must not change what `ROOT` scans)
    because the absolute expectation there is C1's job, not this guard's. **Vacuous today** (both
    sides empty); load-bearing the moment C1 goes green, when the baseline becomes 2.
  AT FREEZE: **passes**, arm 1 with teeth and arm 2 vacuously. Flagged as vacuous so the green tick
  is not read as coverage it does not yet have.

## Adjudication

Written at freeze step 4, before the freeze commit, by a read-only check-reviewer subagent
(`Explore` agent type: no Edit/Write/NotebookEdit). It was given `checks.md`, the test file and the
module, and not the plan. It answered one question per check and per guard: *what could make this
check green that is not the work its criterion names?*

**Residual containment gap, recorded rather than glossed:** the reviewer had `Bash`, so it was not
*structurally* unable to write files — it was instructed not to, and the diff confirms it did not
(only `scripts/test_docs_check.py` changed, by the check-author). This repo's own spike at `d934231`
already established that a read-only agent type contains `Write`/`Edit` but not a verifier with
`Bash`. Naming it here rather than claiming containment the tooling did not provide.

Every strengthening below was made **before** the freeze commit, so none is an amendment and none
costs the tier. All moved in the strict direction; the two simulations are what makes that
checkable rather than asserted.

- **C1: strengthened.** The reviewer found and *ran* a fix shape that greens all 19 tests without
  doing the work — keep the absolute `p.parts` match, but disable exclusions wholesale when
  `ROOT.parts` is tainted (SIM B: 19 passed, exit 0). Actively harmful in this issue's own
  environment: run from any `.worktrees/<branch>/` checkout and `node_modules`, `.venv`, `.git`,
  `__pycache__` and nested worktrees all become scannable. The hole was that C1's tree held nothing
  that must *stay* excluded, so an exact-set assertion over two clean files could not see
  over-scanning. **Closed by** planting `.worktrees/<branch>/docs/design.md` and
  `node_modules/pkg/README.md` inside the tainted `ROOT`: the wrong fix returns 4 and fails, the
  relative-to-`ROOT` fix returns 2 and passes.
- **C2: strengthened.** `SKIP_DIRS |= {".claude"}` plus a relative match greens C2 with no
  worktree-marker logic at all (SIM A: 19 passed, exit 0) — and it also happens to green G3's
  original wording on the main checkout, since all 11 real failures live under `.claude/`. "Skip
  any dot-prefixed component" greens it the same way. The old control could see neither, being
  neither hidden nor named `.claude`. **Closed by** a second worktree at an unremarkable non-hidden
  path (`tools/checkout-b/`, marker only) plus a hidden non-worktree in the control
  (`.github/CONTRIBUTING.md`) that must still be scanned. Together those admit only marker-based
  logic: the name hardcode fails `tools/checkout-b`, the dot-prefix hardcode fails the control.
- **G1: strengthened.** It does guard what it claims and passes for the stated reason. But the
  manifest called it "the guard that blocks the obvious wrong fix", and SIM B is an obvious wrong
  fix it did **not** block — because G1 only ever ran with an untainted `ROOT`, the one
  configuration where the taint branch is never taken. Closed by the same C1 assertion above,
  which exercises the descendant rule under a tainted `ROOT`. G1's own case is kept unchanged; it
  still earns its place for the untainted path.
- **G2: strengthened** (the reviewer said escalate; it is actionable here, so it was acted on
  rather than escalated). Two real defects in the entry, both fixed above: the recorded baseline
  was stale — 113 was measured before the freeze tests existed, the frozen state is 120/117/3 —
  and it concealed a third red test outside the declared tamper surface. `test_gate_test_wiring.py`
  is now in the read-only list, its failure is characterised as self-resolving collateral with the
  assertion cited, and both baselines are recorded so a grader can distinguish "the collateral
  cleared" from "someone edited it".
- **G3: strengthened** (likewise reported as escalate; actionable, so acted on). Its teeth were
  unmeasurable — `main()` prints no count, so "non-zero file count" collapsed to exit status alone,
  which is the null-renders-as-pass shape this project exists to catch — and it was ambiguous about
  *which* repo root, with the two answering oppositely and the wrong one being where the work
  happens. Original wording kept verbatim; discharged by the two-tree, count-printing,
  floor-asserting form above. Strictly harder than the original in both trees, which is the only
  direction a pre-freeze strengthening may move.
- **G4: accepted.** The reviewer went looking for a `.git`-based rule that slips past it and did
  not find one: arm 1 asserts `== TREE_FILES` absolutely on both spellings, so a directory-marker
  rule fails one arm and a file-marker rule fails the other, and only exempting `ROOT` passes both.
  It confirmed the pass is not a fixture accident (both trees genuinely scan 2 files, and
  `ROOT.parts` contains no `.git` in either arm), that arm 2 becomes load-bearing rather than
  staying vacuous once C1 is green, and that there is no cross-arm state bleed. Noted and
  deliberately not acted on: G4 never exercises `.git` at a descendant that is *not* a worktree
  (a vendored submodule), which is outside C2's criterion.

**Residual the checks cannot close, named so review can carry it.** An implementer willing to
hardcode the *fixture's own path names* — `if "checkout-b" in p.parts or ".claude" in p.parts` —
greens C2 with no marker logic. No set of planted worktrees closes this in principle: a fixture can
plant only finitely many spellings, and naming them defeats any of them. Two spellings plus the
hidden-non-worktree control raise the cost enough that the cheat is visible on sight; a third
spelling would not change the category. **This is a review-catches-it item, not a
test-catches-it item** — a reviewer should confirm the diff contains no reference to
`checkout-b`, `.claude`, or `.github`.

Everything *mechanism*-shaped that the check-author could construct now dies against the
strengthened set: allowlisting `docs/**` plus top-level (dies on `.github/CONTRIBUTING.md`), depth
rules and dot-prefix rules (the control sits at the same depth and is hidden), name additions (die
on `tools/checkout-b`), taint-disables-exclusions and taint-drops-the-offending-name (both die on
C1's 4-vs-2, because C1's nested excluded directory deliberately reuses `ROOT`'s own component
name), and `parts = [x for x in p.parts if x not in ROOT.parts]` (dies the same way). The surviving
implementations are the two intended ones: exclusions computed on `p.relative_to(ROOT)`, and
worktree detection by a `.git` entry from which `ROOT` itself is exempt.

**Mechanics, checked and clean.** No new case calls `check_links`/`check_tables`/`check_counts`, so
`failures`/`skips` stay empty regardless, and `isolate`'s reset still runs for all seven (autouse).
`ROOT` is only ever set through `monkeypatch.setattr`, so it is restored per test; each test owns
its own `tmp_path`. Results were identical running the file alone and inside the full suite, so no
ordering dependence. `scanned()` would raise `ValueError` rather than silently pass if a fix made
`md_files()` return paths outside `ROOT` — it fails loudly, which is right.

## Tamper verdict

`clean`, taken against the tree that ships and re-runnable by anyone:

```
git diff 2d7c4a6 -- scripts/test_docs_check.py scripts/test_gate_test_wiring.py   # empty
```

`2d7c4a6` is an ancestor of the pushed head (`git merge-base --is-ancestor` confirms), and the
branch was not squashed, so a reviewer can re-run the command rather than take this record on
trust. `origin/main` had not advanced at rebase time, so the freeze sha needed no re-anchoring.

Confirmed independently by the verifier subagent, which ran both diffs itself and read
`git diff 2d7c4a6 --stat` for collateral: **no test file appears in the diff at all.** The only
non-session-artifact change is `scripts/docs_check.py`.

**The differences in `checks.md` itself, sanctioned and named rather than left for a reader to
notice.** Two hunks: the `Frozen at` header, written in the follow-up commit `a842815` because a
commit cannot contain its own hash; and this `## Tamper verdict` section appended at the end.
`frozen-checks.md` names both as inert appends. **No CRITERION line, CHECK command, guard command
or `AT FREEZE` line differs.** `checks.md` is not in `Check files`, so it is outside the tamper
scope either way.

*Don't state a count here.* An earlier draft of this paragraph claimed the file "differs by two
lines" — wrong, and wrong in a self-referential way that no care would have prevented: the diff is
larger than any figure written inside it, because the figure is part of what it measures. The
verifier caught it. `git diff 2d7c4a6 -- <this file>` is the only honest answer, which is the
project's own rule (*cite the command, not the number*) landing on the tamper record itself.

## Amendments

_(Append-only. Empty — no check was changed after the freeze commit. Every strengthening in the
Adjudication above was made pre-freeze, which is why none appears here.)_
