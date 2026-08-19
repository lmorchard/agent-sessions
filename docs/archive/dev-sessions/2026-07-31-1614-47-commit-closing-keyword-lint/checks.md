# Frozen acceptance checks

**Source:** https://github.com/lmorchard/agent-sessions/issues/47
**Frozen at:** 945467b (2026-07-31)
**Check files — read-only from Phase 1 onward:**
- `scripts/test_commit_lint.py`

## C1

CRITERION: GIVEN a commit-message body containing a closing keyword inside backticks, WHEN the
detector runs, THEN it SHALL report that commit; AND GIVEN a body whose only closing keyword is an
ordinary trailing `Closes #N`, it SHALL NOT report it.

CHECK: `uv run pytest scripts/test_commit_lint.py` — fixtures for both, asserting the quoted form
is reported and the genuine form is not. The negative case is the load-bearing half: a detector that
flags every `Closes #N` would fire on every legitimate commit in this repo and be disabled within a
day, which is what happened to the whole-repo cleanliness idea in #36.

AT FREEZE: fails — pytest exits 2 (collection error), not 5 (nothing collected):

```
scripts/test_commit_lint.py:72: in <module>
    import commit_lint  # noqa: E402
E   ModuleNotFoundError: No module named 'commit_lint'
```

**Correct reason, and worth stating why an ImportError qualifies here.** Normally an import
error means "not yet a check" — it fails for a setup reason unrelated to the criterion. Here
the absent module *is* the criterion's condition: C1's DEMONSTRATED FAILING is precisely that
no commit-message detector exists. The check will pass only once a detector exists that
discriminates, which the per-occurrence and real-history tests enforce.

## C2

CRITERION: WHEN the detector runs over the commits on the current branch that are not yet on
`origin/main`, THEN a quoted closing keyword SHALL fail the check with a non-zero exit.

CHECK: the same test file, plus running the detector over a fixture range; and `make check`
exits non-zero with such a commit present, 0 without — the shape #28's C3 already proved works.

AT FREEZE: fails — same collection error; the range-scanning and entry-point tests
(`test_range_scan_finds_the_dirty_commit_and_not_the_clean_one`,
`test_entry_point_exits_non_zero_when_a_quoted_keyword_is_present`, and their clean/empty-range
counterparts) never ran, because `scripts/commit_lint.py` does not exist to be invoked as a
process. `make check` has no `commit-lint` target at freeze, so the second half of the check —
"`make check` exits non-zero with such a commit present" — has nothing to exercise either.

## Guards

(Pass today; must keep passing. Not criteria — they can't fail at freeze.)

- **G1:** Every genuine `Closes #N` in this repo's history stays unreported. Run the detector over
  `--all`: it SHALL report **exactly one occurrence** — the quoted `Closes #7` in commit `2cbe106`.
  Verified 2026-07-31: history carries ten genuine closing references (`#4`, `#5`, `#11`, `#18`, `#20`,
  `#23`, `#36`, plus `#15`/`#16`/`#22` sharing commit `d5bdd30`), and none of them may be reported.
  **The reported occurrence must be distinguishable from `2cbe106`'s own genuine `Closes #23`** — that
  one commit body carries both, so a guard counting flagged *commits* rather than flagged *occurrences*
  passes while the detector fires for the wrong reason. **This is the guard that stops the fix being
  useless**, because the cheap way to green C1 is to flag every closing keyword.

  *Status at freeze:* the detector does not exist, so G1 cannot be run as written. Its **premise** was
  re-verified instead, at freeze, by an independent scan of `git log --all` (recorded below). G1 becomes
  runnable in Phase 1 and must pass then. Recorded here as a premise-verified guard rather than a
  passing one — a null must not render as a positive.

- **G2:** `make check` stays green on a clean history, and `python3 scripts/docs_check.py` exits 0.
  Pass today.

  *Status at freeze:* **passes.** `make check` at the freeze tree ends `all checks passed`; the
  `driver-test` leg reports `21 passed, 0 failed`, `docs-check` reports `links resolve, tables
  well-formed, counts match`, `assertion-lint` reports clean over 2 files. Note the frozen test
  file is not yet wired into `gate-test`, which is why `make check` is green while
  `uv run pytest scripts/test_commit_lint.py` fails — wiring it in is Phase 1 work and is what
  makes C2's "`make check` exits non-zero" half real.

- **G3:** The detector does not flag *itself*. Its own source and tests will contain quoted closing
  keywords as fixtures — `assertion_lint.py` solved the identical problem by scoping what it lints, and
  it is the third time this trap has appeared. Verified today: `assertion_lint` contains its own
  pattern 6 times and reports itself 0 times.

### G1's premise, re-verified at freeze (2026-07-31)

`git log --all` scanned for `\b(close[sd]?|fix(es|ed)?|resolve[sd]?)\s+#\d+`, case-insensitive.
Eleven occurrences across nine commits:

| commit | reference | context |
|---|---|---|
| `1a2e665` | `Closes #36` | genuine — own line |
| `2cbe106` | `Closes #7` | **quoted** — inline, inside backticks, mid-sentence |
| `2cbe106` | `Closes #23` | genuine — own line |
| `9b660c8` | `Closes #11` | genuine — own line |
| `b6490f0` | `Closes #18` | genuine — own line |
| `1442c92` | `Closes #20` | genuine — own line |
| `d5bdd30` | `Closes #15` | genuine — own line |
| `d5bdd30` | `Closes #16` | genuine — own line |
| `d5bdd30` | `Closes #22` | genuine — own line |
| `dde1803` | `Closes #5` | genuine — own line |
| `da9a782` | `Closes #4` | genuine — own line |

Ten genuine, one quoted. Matches G1's enumeration exactly, including the correction note.

## Amendments

(Append-only. Empty unless an amendment was made.)
