<!-- agent-session:spec -->

`make gate-test` does not run `scripts/test_assertion_lint.py`, so `assertion_lint`'s own tests have
never run under `make check`.

Verified 2026-07-31 on `main` at `7cdd4a5`:

```
$ grep -A2 '^gate-test:' Makefile
gate-test:
	@uv run --quiet pytest driver/test_gate.py scripts/test_docs_check.py scripts/test_run_progress.py scripts/test_commit_lint.py scripts/test_commit_lint_edges.py

$ ls scripts/test_*.py
scripts/test_assertion_lint.py      <-- exists, not listed above
scripts/test_commit_lint.py
scripts/test_commit_lint_edges.py
scripts/test_docs_check.py
scripts/test_run_progress.py

$ uv run pytest scripts/test_assertion_lint.py -q
7 passed
```

So the tests exist, they pass, and nothing runs them. `make check` is green either way.

## Why this is worth its own issue

**`assertion_lint` is a detector, and an untested detector is the thing this repo keeps paying for.**
It is the mechanism that enforces [defect class 5](https://github.com/lmorchard/agent-sessions/blob/main/docs/findings.md)
— "a test that greps its subject for a literal is a spelling check, not a test" — and it is the
mitigation named in `CLAUDE.md` for that class. A silent regression in it would restore the whole
defect class with every suite still green.

**It was also asserted to be running, in writing, and the claim was false when written.** Issue #47's
spec offered `scripts/test_assertion_lint.py` as its ORACLE-EXISTS-NOW precedent, with the words
*"already run by `make gate-test`"*. The run that implemented #47 checked, found otherwise, and
surfaced it in PR #49's References rather than fixing it — correctly, as a different issue's work.
That is defect class 1 in the ordinary place: the row cited a command, and the evidence offered was
not that command's output.

## Suggested shape (not a decision — needs intake)

1. Add `scripts/test_assertion_lint.py` to the `gate-test` recipe.
2. Consider whether the recipe should stop being a hand-maintained file list at all. A list of test
   paths in a Makefile is a census, and a census of a growing set is a staleness hazard — the same
   shape as the assertion counts that went wrong twice in opposite directions. A glob over
   `scripts/test_*.py` and `driver/test_*.py` would make "a new test file is not run" unreachable
   rather than merely fixed once.
3. If a glob is adopted, the discriminating check is not "the suite passes" — it is that adding a
   new failing test file to the directory makes `make check` fail without anyone editing the
   Makefile.

Note that item 1 alone leaves the general defect in place, and item 2 is what actually closes it.
Which of the two is in scope is the decision intake should settle.

~~Not triaged: no spec marker, so the board-driver will skip it until it goes through intake.~~

**Triaged 2026-08-01** — the marker now leads this body and the criteria are below.

---

## Verifiable acceptance criteria

- **C1.** WHEN `make gate-test` runs, THEN it SHALL collect every test file matching
  `driver/test_*.py` and `scripts/test_*.py`.
  **CHECK:** the collected count under `gate-test`'s own arguments equals the collected count under
  the globs — `uv run pytest <gate-test args> --collect-only` vs
  `uv run pytest driver/test_*.py scripts/test_*.py --collect-only`.
  **Stated as equality between two live measurements, never as a pinned number**, per defect class 3:
  the invariant is "the recipe runs everything that exists", and any literal total goes stale the next
  time a test is added.
  **DEMONSTRATED FAILING 2026-08-01:** the recipe collects **104**, the globs collect **111**. The
  difference is exactly `scripts/test_assertion_lint.py`'s 7 tests.
  **ORACLE EXISTS NOW:** pytest and `--collect-only`. Nothing to build.

- **C2.** WHEN a new test file matching those globs is added, THEN `make gate-test` SHALL run it with
  **no edit to the `Makefile`**.
  **CHECK:** with a temporary failing test file placed in `scripts/`, `make gate-test` exits non-zero;
  with it removed, exit 0. The fixture must remove the file on exit, including on failure.
  **DEMONSTRATED FAILING:** the recipe names five files literally, so a sixth is unreachable — which
  is how `test_assertion_lint.py` came to exist, pass, and never run.
  **This is the criterion that closes the class**; C1 alone is satisfiable by appending one filename,
  which fixes the instance and leaves the next one available.
  **Note the mechanism writes into `scripts/` during the check.** That is a small hazard of its own —
  a killed run could leave a stray failing test file behind. Prefer a fixture whose cleanup is a
  `trap`, and say so at freeze rather than discovering it.

## Regression guards

- **G1.** Every test that passes today still passes: running the globs directly
  (`uv run pytest driver/test_*.py scripts/test_*.py`) is green, with no test lost, newly skipped or
  newly failing. Passes today — 111 collected, all passing, verified 2026-08-01.
- **G2.** `make check` exits 0. Passes today.
- **G3.** `make check` still runs every step it runs today — `driver-check`, `driver-test`,
  `park-test`, `skill-readonly`, `docs-check`, `assertion-lint`, `commit-lint`. Stated as "every step
  still reports" rather than as a count, because the cheap way to make a Makefile change green is to
  drop a step. Passes today.

## Tier: auto-ok

**Trigger 1 does not fire.** Both criteria are counted or exit-status assertions with pytest as the
oracle, and C1 was demonstrated failing by running it.

**Trigger 2 does not fire.** The work lands in `Makefile` and `scripts/`, both on `CLAUDE.md`'s
drivable allowlist. Not `driver/gate.py`, not `skills/**`.

## Design decisions

- **Decision:** replace the hand-maintained file list with globs, rather than appending the one
  missing filename.
  - **Why:** the omission is not the defect — the *census* is. A list of test paths in a recipe is a
    hand-maintained inventory of a growing set, which is the same staleness shape that produced two
    wrong assertion counts in opposite directions and the `22`-vs-`21` manifest correction in PR #54.
    Appending a filename fixes one instance and leaves the mechanism that generated it.
  - **Rejected:** adding `scripts/test_assertion_lint.py` to the recipe and stopping. It would satisfy
    C1 and not C2, which is exactly why C2 is written.

## What we're NOT doing

- **Changing what any test asserts.** This is a wiring fix; a test that starts running and fails is a
  pre-existing break to report, not to fix here.
- **Globbing `driver/test-*.sh`.** The bash suites are wired separately through `driver-test` and
  `park-test` and are not affected.
