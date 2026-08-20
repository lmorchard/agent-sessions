# Frozen acceptance checks

**Source:** https://github.com/lmorchard/agent-sessions/issues/62
**Frozen at:** (pending — recorded in the follow-up commit)
**Check files — read-only from Phase 1 onward:**
- `scripts/test_docs_check.py`

## C1
CRITERION: GIVEN a `ROOT` whose own path contains a component named in `SKIP_DIRS`, WHEN
`docs_check` enumerates markdown files, THEN it SHALL still find the files beneath that `ROOT`.
CHECK: `uv run pytest scripts/test_docs_check.py -k worktree` reports `0 failed`.
AT FREEZE: fails — `12 deselected in 0.01s`, exit 5. Run 2026-08-01 from the repo root.

## Guards
(Pass today; must keep passing. Not criteria — they can't fail at freeze.)

- G1: exclusion still works for *descendants* — a `.worktrees/` directory **inside** `ROOT` is
  still skipped, so the obvious wrong fix (dropping `.worktrees` from `SKIP_DIRS`) is blocked.
  CHECK: with `ROOT = <tmp>` containing `<tmp>/keep.md` and `<tmp>/.worktrees/x.md`,
  `md_files()` returns exactly `['keep.md']`.
  AT FREEZE: passes — `scanned: ['keep.md']`. Run 2026-08-01.
- G2: all existing `docs_check` cases pass unchanged — no case lost, newly skipped or newly
  failing. CHECK: `make gate-test`.
  AT FREEZE: passes — `113 passed in 5.92s`. Run 2026-08-01.
- G3: `python3 scripts/docs_check.py` from the repo root still reports the same verdict on the
  real tree, over a non-zero number of files. CHECK: exit 0, and `len(md_files())` is non-zero.
  AT FREEZE: passes — `docs-check: links resolve, tables well-formed, counts match`, exit 0,
  `md files scanned = 108`. Run 2026-08-01.
- G4: the project's own gates stay green. CHECK: `make check` reports `all checks passed`.
  AT FREEZE: passes — `all checks passed`. Run 2026-08-01.

## Adjudication

Three independent read-only reviewers, dispatched per `frozen-checks.md` freeze step 4 — manifest
plus repo, no plan, no rationale, no hint that any check was seeded. **No check was accepted by
any reviewer.**

- **C1 — escalated (3/3).** The seeded check. All three named the cheapest green exactly:
  `def test_worktree_...(): assert True`. All three also found the unseeded `0 failed` defect and
  the read-only self-contradiction.
- **G1 — strengthened (2/3), escalated (1/3).** Stated as prose with a hand-run transcript rather
  than a named artifact, and `md_files()` returns `Path`s so `== ['keep.md']` is not literally
  runnable — both are real defects in the fixture as authored.
- **G2 — escalated (2/3), strengthened (1/3).** The criterion names "lost, newly skipped or newly
  failing"; `make gate-test` detects only the third.
- **G3 — strengthened (2/3), escalated (1/3).** "Non-zero" is satisfied by 1 and by 108.
- **G4 — strengthened (3/3).** `all checks passed` is an unconditional `@echo`; dropping a
  prerequisite from `check:` keeps it green.

**Why this round is recorded as a failed instrument rather than a reviewer failure.** Read by
hand, every finding is correct. The four non-seeded checks were taken from issue #62's
already-triaged body (plus a G4 in this repo's house style) on the assumption that ratified
checks are strong; they are not. The round therefore could not distinguish *"the reviewer flags
everything"* from *"everything here is flaggable"*, which is a non-discriminating fixture.
Round 2 tightens all four guards and re-runs.

One reviewer's cross-cutting note, correct and not seeded: the whole manifest is satisfiable by a
single commit adding `def test_worktree_root(): assert True` and changing nothing else.

## Amendments
(Append-only. Empty unless an amendment was made.)
