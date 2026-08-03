# Plan — #62 `docs-check` scans zero files inside a worktree

**Source:** https://github.com/lmorchard/agent-sessions/issues/62
**Tier:** `auto-ok` (body and label agree)
**Session:** `docs/dev-sessions/2026-08-03-1109-62-docs-check-worktree-root/`
**Worktree:** `.worktrees/fix/62-docs-check-worktree-root`, branch `fix/62-docs-check-worktree-root`

## Phase 0 — freeze (DONE)

Frozen at `2d7c4a6`; sha recorded in `a842815`. See `checks.md` for the manifest, the
`AT FREEZE` evidence per criterion and guard, and the adjudication.

- **Advances:** nothing — authors the oracle.
- **Check files, read-only from here on:** `scripts/test_docs_check.py`,
  `scripts/test_gate_test_wiring.py`.
- State at freeze: `uv run pytest driver/test_*.py scripts/test_*.py` → 120 collected,
  117 passed, 3 failed, 0 skipped. `make check` red.

## Phase 1 — exclusions relative to `ROOT`

The defect C1 names: one `SKIP_DIRS` entry means "skip a subtree" from the repo root and
"skip everything" from inside it, because the match is against `p.parts` — the *absolute*
path's components, `ROOT`'s own included.

- **Advances:** C1. Holds G1, G4.
- **Change:** in `scripts/docs_check.py`'s `md_files()`, match `SKIP_DIRS` against the
  components of `p.relative_to(ROOT)` rather than `p.parts`. `SKIP_DIRS` keeps every entry it
  has today — `.worktrees` included, which G1 requires and which the spec is explicit about.
- **Why this and not the alternatives:** the spec settled it. Removing `.worktrees` from
  `SKIP_DIRS` greens C1 and reintroduces cross-branch linting (G1 blocks it). `git rev-parse`
  adds a subprocess to a module whose stated constraint is stdlib-only. `git ls-files` would
  fix both criteria and delete the name list, but reshapes the `tmp_path` fixture every
  existing case depends on — trading a known oracle for a rewritten one inside the change that
  needs the oracle. The spec defers it explicitly.
- **Verify:** (commit `42ad66f`)
  - [x] `uv run --quiet pytest scripts/test_docs_check.py -k c1 -v` — both C1 cases pass
  - [x] `uv run --quiet pytest scripts/test_docs_check.py -k "g1 or g4" -v` — all three pass,
        and `test_g4_a_dot_git_entry_at_root_changes_nothing_under_an_excluded_name` is now
        load-bearing rather than vacuous (its baseline becomes 2).
        Observed together with C1: `5 passed, 14 deselected`.
  - [x] C2 still fails — this phase is not supposed to fix it, and a C2 that went green here
        would mean the relative match is over-broad. Observed: `1 failed, 18 passed`, the one
        being `test_c2_a_nested_git_worktree_is_not_scanned`.

## Phase 2 — worktree detection by `.git` marker

The defect C2 names: `md_files()` decides what is a worktree by matching directory *names*, and
no name list can be right. `.worktrees` is the fallback this repo never uses;
`.claude/worktrees/` is what Claude Code actually creates.

- **Advances:** C2. Holds C1, G1, G4.
- **Change:** additively to `SKIP_DIRS`, skip any *descendant* directory of `ROOT` that
  contains a `.git` entry (file or directory). `ROOT` itself is exempt — that exemption is the
  whole of G4, since a main checkout carries `.git` as a directory and a worktree as a file, so
  a rule applied to `ROOT` would scan zero files and reintroduce C1 through C2's fix.
- **Why a marker and not more names:** a linked worktree root always carries a `.git` file
  containing `gitdir: …`; a nested checkout carries a `.git` directory. The marker identifies
  the *class* — any nested working tree, whatever it is called and wherever a tool puts it —
  and removes a hand-maintained inventory, which is the shape #50 argued against. Stdlib only,
  no subprocess.
- **Scope discipline:** `.pytest_cache` is *not* in `SKIP_DIRS` and its `README.md` is scanned.
  Noticed while grounding G3's count floor; out of scope, and G3 asserts a floor rather than an
  equality precisely so this does not have to be touched. Recorded in `notes.md` for a future
  session, not fixed here.
- **Verify:** (commit `9989052`)
  - [x] `uv run --quiet pytest scripts/test_docs_check.py -k c2 -v` — case and control pass.
        Run by full node id rather than `-k`: `2 passed`.
  - [x] `uv run --quiet pytest scripts/test_docs_check.py -v` — `19 passed`
  - [x] `uv run --quiet pytest driver/test_*.py scripts/test_*.py` — `120 passed`, 0 skipped
        (G2 discharged; the `test_gate_test_wiring.py` collateral cleared on its own, as
        predicted, with no edit to that file)

## Phase 3 — discharge the guards against the real tree

The frozen checks are synthetic by construction. G3 is the only check that touches the actual
repository, and it is the one the reviewer found unrunnable as worded — so it gets its own
phase rather than a checkbox on Phase 2.

- **Advances:** nothing new. Discharges G2, G3.
- **Verify** (all four cells; `checks.md`'s G3 entry is authoritative on the form):
  - [x] worktree root: `python3 scripts/docs_check.py` exits 0 — observed `exit=0`, and
        `docs-check: links resolve, tables well-formed, counts match`
  - [x] worktree root: `python3 -c "import sys;sys.path.insert(0,'scripts');import docs_check;print(len(docs_check.md_files()))"` prints ≥ 100 — observed **116**
        (was **0** at freeze, against 115 markdown files on disk)
  - [x] main checkout, `.claude/worktrees/` copy still present: exits 0 — **0 failures, down
        from 11**. C2's real-world payoff.
        *How it was run, because it matters:* the fix is on this branch, so the main checkout's
        own `docs_check.py` is still the buggy one. The fixed module was imported with `ROOT`
        set to the main checkout — exactly what `Path(__file__).resolve().parent.parent` would
        compute there — and `check_links` / `check_tables` / `check_counts` run as `main()` runs
        them. Recorded rather than glossed: this cell is the fixed *logic* against the real
        tree, not the fixed *file* in place, and it becomes the latter on merge.
  - [x] main checkout: the same count command prints ≥ 100 — observed **113** (was 226 at
        freeze, inflated by the copy). Also asserted, beyond G3's letter: **0** files scanned
        from any nested worktree, and all **82** session records frozen-exempt again — the
        exemption C2 broke.
  - [x] `make check` green in the worktree — `all checks passed`. First time in this project's
        history that a run's `project-gates` row includes a `docs-check` that examined
        anything.

## Phase 4 — session notes

- **Advances:** nothing. Provenance.
- `notes.md`: what was fixed, what the reviewer caught, the two guards that failed at freeze and
  why, and the out-of-scope observations (`.pytest_cache`; `assertion_lint` / `commit_lint`
  unaudited per the spec's "What we're NOT doing").
- **Verify:**
  - [x] `make docs-check` passes on the new session docs — `exit=0`. Confirmed as presence, not
        just exit status: all **4** of this session's files (`spec.md`, `checks.md`, `plan.md`,
        `notes.md`) are in the scanned set, each `frozen-exempt: True`. So link and table checks
        now cover them; freshness stays exempt by design, `docs/dev-sessions/` being a
        historical record. Post-fix this is the first time a run's own session documentation has
        ever actually been scanned — the issue's point, stated as a result rather than assumed.

## TDD posture

The frozen acceptance tests already exist and are read-only, and they are red for exactly the
two behaviours Phases 1 and 2 add. So each phase is test-first by construction; no additional
unit tests are planned. If a phase needs scaffolding tests of its own they are the
implementer's and freely editable — but nothing in `Check files` is.

## Self-review

- **Criteria coverage, both directions.** C1 → Phase 1. C2 → Phase 2. Every phase either
  advances a criterion (1, 2) or discharges guards / records provenance (0, 3, 4), and no
  criterion is unclaimed. Phases 3 and 4 advance no `Cn` deliberately: G3's strengthened form is
  four commands across two working directories, which does not fit under a criterion's phase,
  and Phase 4 is the artifact the skill requires.
- **Checks cited by command.** Every automated box above is a runnable command, not "tests
  pass". G3's four cells are quoted from `checks.md` rather than paraphrased.
- **Placeholders.** None. No "TBD", no "add error handling", no reference to a helper no phase
  defines.
- **Type/name consistency.** The plan touches exactly two names in `docs_check.py`, both
  existing: `md_files()` and `SKIP_DIRS`. `FROZEN` and `is_frozen()` are unchanged — C2's
  exemption damage is a *consequence* of over-scanning, so fixing the enumeration fixes the
  exemption without touching it. Worth being explicit, because "frozen records lose their
  exemption" reads like an `is_frozen()` bug and is not one.
- **Ordering.** Phase 1 before Phase 2 is load-bearing, not cosmetic: G4 is the trap that
  Phase 2 walks into, and it only has teeth once Phase 1 is green (its excluded-name arm is
  vacuous while C1 fails). Doing Phase 2 first would mean adding `.git` logic under a guard that
  cannot yet catch the mistake it exists to catch.
- **One risk accepted and named.** The two phases pull in opposite directions on the same
  function — Phase 1 relaxes matching, Phase 2 adds an exclusion — so each phase re-runs the
  other's checks, not only its own. That is why Phase 2's box asserts the whole file at 19/19
  rather than just C2.
