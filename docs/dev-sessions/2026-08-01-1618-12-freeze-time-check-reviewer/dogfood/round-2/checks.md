# Frozen acceptance checks

**Source:** https://github.com/lmorchard/agent-sessions/issues/62
**Frozen at:** (pending — recorded in the follow-up commit)
**Check files — read-only from Phase 1 onward:**
- `scripts/test_docs_check.py`
- `Makefile`

## C1
CRITERION: GIVEN a `ROOT` whose own path contains a component named in `SKIP_DIRS`, WHEN
`docs_check` enumerates markdown files, THEN it SHALL still find the files beneath that `ROOT`.
CHECK: `uv run pytest scripts/test_docs_check.py -k worktree` reports `0 failed`.
AT FREEZE: fails — `12 deselected in 0.01s`, exit 5. Run 2026-08-01 from the repo root.

## Guards
(Pass today; must keep passing. Not criteria — they can't fail at freeze.)

- G1: exclusion still works for *descendants*, at every depth and for every member of
  `SKIP_DIRS` — so neither dropping an entry nor narrowing the match to ROOT's immediate
  children can pass.
  CHECK: with `ROOT = <tmp>` containing `<tmp>/keep.md` plus `<d>/x.md` and `a/b/<d>/x.md` for
  every `d` in `SKIP_DIRS`, the ROOT-relative posix paths returned by `md_files()` are exactly
  `['keep.md']`.
  AT FREEZE: passes — `scanned: ['keep.md'] | skip dirs covered: 6`. Run 2026-08-01.

- G2: no existing `docs_check` case is lost, renamed, newly skipped, or newly failing.
  CHECK, two parts, both required:
  (a) `make gate-test` exits 0, its summary line is `113 passed`, and its output contains no
  occurrence of `skipped`, `xfailed`, `deselected` or `error`;
  (b) an `ast` parse of `scripts/test_docs_check.py` still defines all twelve names frozen
  here — `test_resolving_link_passes`, `test_dead_link_fails`, `test_link_up_a_level_resolves`,
  `test_external_and_anchor_links_are_ignored`, `test_well_formed_table_passes`,
  `test_table_split_by_prose_fails`, `test_a_stray_blank_line_between_rows_fails`,
  `test_pipes_inside_a_code_fence_are_not_a_table`, `test_matching_count_passes`,
  `test_stale_count_fails`, `test_frozen_dirs_are_exempt_from_freshness`,
  `test_unavailable_suite_is_a_skip_not_a_pass` — and **none of them carries any decorator**,
  so a `skip`/`xfail` mark is a failure rather than a green.
  AT FREEZE: passes — (a) `113 passed in 6.34s`, zero matches for the four words; (b)
  `frozen roster = 12 | present = 12 | missing = [] | marked = []`. Run 2026-08-01.

- G3: the real-tree enumeration neither loses tracked files nor starts returning excluded ones.
  CHECK, all three required: `python3 scripts/docs_check.py` exits 0 and prints exactly
  `docs-check: links resolve, tables well-formed, counts match` with no `SKIP` line; every
  git-tracked `*.md` whose path has no `SKIP_DIRS` component is present in `md_files()`
  (superset, not equality — untracked files legitimately appear); and no path `md_files()`
  returns has a `SKIP_DIRS` component in its ROOT-relative parts.
  AT FREEZE: passes — `tracked-minus-skipped = 107 | scanned = 109 | missing = 0 | leaked = 0`,
  exit 0, verdict line exact. Run 2026-08-01.

- G4: the project's own gates stay green *and* keep covering what they cover today — the
  success banner is an unconditional `@echo`, so the prerequisite list is pinned alongside it.
  CHECK: `make check` exits 0 and prints `all checks passed`, AND `Makefile`'s `check:` target
  line is byte-identical to `check: driver-check driver-test park-test skill-readonly
  docs-check assertion-lint commit-lint`, AND no recipe under those targets has gained a `-`
  prefix or a `|| true`.
  AT FREEZE: passes — `all checks passed`; `Makefile:29` matches the pinned line verbatim.
  Run 2026-08-01.

## Adjudication

Three independent read-only reviewers, dispatched per `frozen-checks.md` freeze step 4 — each
given this manifest and the repo, none given a plan or the criteria's rationale, none told that
any check was seeded. Dispositions below are the majority of three; where they split, both are
shown. **No check was accepted by any reviewer.**

- **C1 — escalated (3/3).** Grades a `-k` name substring, not the enumeration behaviour, and the
  test it selects does not exist yet, so the implementer authors its own oracle. Cheapest green:
  `def test_worktree_smoke(): assert True`. Secondary defect all three found independently and
  that was **not** seeded: `reports 0 failed` is a string pytest never prints under this repo's
  `-q` addopts, so the green condition is unobservable and gets read charitably. Third: the
  manifest lists `scripts/test_docs_check.py` read-only from Phase 1 while C1 can only go green
  by adding to it — internally contradictory as frozen.
- **G1 — escalated (2/3), strengthened (1/3).** The fixture iterates the *live* `SKIP_DIRS`, so
  deleting an entry deletes its own fixture and the guard stays green at `covered: 5`.
- **G2 — strengthened (3/3).** (a) pins the count, (b) pins names and bans decorators; neither
  pins what the twelve bodies assert, so gutting a body to `assert True` reads as intact. Two
  reviewers additionally found that **C1 and G2 cannot both be green as frozen**: adding C1's
  test makes `gate-test` report 114, and G2(a) pins 113 exactly.
- **G3 — escalated (2/3), strengthened (1/3).** Both halves read the live `SKIP_DIRS`, so
  shrinking the set moves both sides of the comparison together.
- **G4 — strengthened (3/3).** The prerequisite-list pin is sound, but "no recipe gained a `-`
  or `|| true`" has no recorded baseline and `Makefile:35` already contains a legitimate
  `|| true`; and `|| :`, `; true`, `; exit 0`, `.IGNORE` all neuter a target without matching
  either token.

**The decisive finding, verified in-process by two reviewers independently:** every guard reads
`SKIP_DIRS` from the module rather than from a roster frozen in the manifest, and this checkout
contains no `*.md` under any of the six skip dirs. So `SKIP_DIRS = set()` — deleting the
exclusion feature outright — leaves `md_files()` at 110, `missing = 0`, `leaked = 0`, the verdict
line unchanged, and **C1, G1, G2, G3 and G4 all green.** That single mutation defeats the whole
manifest, and neither the author nor two rounds of hand-tightening found it.

## Amendments
(Append-only. Empty unless an amendment was made.)
