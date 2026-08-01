# Frozen acceptance checks

**Source:** https://github.com/lmorchard/agent-sessions/issues/50
**Frozen at:** `a06c74d` (2026-08-01)

**Check files — read-only from Phase 1 onward:**
- `scripts/test_gate_test_wiring.py`

Both criteria reduce to runnable pytest tests, so `Check files` is non-empty and the ordinary
`git diff <freeze-sha> -- <check files>` tamper diff applies. The substitutes in
`frozen-checks.md`'s "When the criteria are commands, not test files" are **not** in play.

**Note on the oracle/implementation boundary.** The implementation edits `Makefile`'s `gate-test`
recipe; the checks live in `scripts/test_gate_test_wiring.py`. Those are disjoint, so
`frozen-checks.md`'s "When the work must edit its own oracle" section does **not** apply either.
What *is* unusual here is that the frozen check invokes the recipe it is grading — see the
recursion note under C2.

## C1

CRITERION: WHEN `make gate-test` runs, THEN it SHALL collect every test file matching
`driver/test_*.py` and `scripts/test_*.py`.

CHECK: `uv run pytest scripts/test_gate_test_wiring.py::test_gate_test_collects_every_globbed_test -q`
passes. The test derives `gate-test`'s own pytest arguments from `make -n gate-test` at run time
and compares `--collect-only` totals against the two globs.

**Stated as equality between two live measurements, never as a pinned number**, per defect class 3:
the invariant is "the recipe runs everything that exists", and any literal total goes stale the next
time a test is added. The test therefore embeds **no count and no filename** — deriving the recipe's
arguments from `make -n` rather than restating them is what keeps this from being a spelling check
(defect class 5).

AT FREEZE: **fails, correct reason.** `assert 104 == 113` — a real assertion failure at the
criterion's own assertion (line 176), reached only after `make -n` parsed and both collections
exited 0. Not a collection error, not a setup error. The message names the omitted files:

```
    matched by the globs but NOT run by the recipe:
      scripts/test_assertion_lint.py (7 tests)
      scripts/test_gate_test_wiring.py (2 tests)
    run by the recipe but NOT matched by the globs:
      (none)
```

The glob side reads **113**, not the issue's 111, because the two frozen checks in this new file
are themselves matched by `scripts/test_*.py`. That is correct and not a discrepancy: the issue
measured 111 before this file existed. The criterion is an equality between two live measurements
precisely so that adding files cannot invalidate it.

ORACLE EXISTS NOW: pytest and `--collect-only`. Nothing to build. Confirmed by running both
sides by hand on `7309f61`: recipe **104**, globs **111**, difference exactly
`scripts/test_assertion_lint.py`'s 7 tests.

## C2

CRITERION: WHEN a new test file matching those globs is added, THEN `make gate-test` SHALL run it
with **no edit to the `Makefile`**.

CHECK: `uv run pytest scripts/test_gate_test_wiring.py::test_a_new_test_file_is_run_without_a_makefile_edit -q`
passes. With a temporary failing test file placed in `scripts/`, `make gate-test` exits non-zero;
with it removed, exit 0. The `Makefile` is not touched between the two arms.

**This is the criterion that closes the class**; C1 alone is satisfiable by appending one filename,
which fixes the instance and leaves the next one available.

**Cleanup hazard, stated at freeze as the spec asked.** The check writes a failing test file into
`scripts/` and a killed run could strand it, which would then fail `make check` for everyone. The
Python equivalent of the spec's `trap` is a pytest fixture whose teardown runs in a `finally`, so
cleanup happens on assertion failure, on error, and on `KeyboardInterrupt`. Teardown uses
`unlink(missing_ok=True)` so a re-run is not blocked by its own debris. Not covered: `SIGKILL`.
The residual failure is loud and self-announcing (a test named as a probe fails in `scripts/`), not
silent, which is the right direction for it to fail in.

**Recursion hazard, found at plan time rather than discovered at execute.** The check invokes
`make gate-test`, and the check's own file matches `scripts/test_*.py` — so once the recipe globs,
the inner run collects this module and re-invokes the recipe, unbounded. The inner invocation
therefore sets `AGENT_SESSION_GATE_TEST_INNER=1`, and this module skips itself when that variable
is set. The guard is depth-limiting only: it is never set in an ordinary `make gate-test` /
`make check` run, so no test is skipped in the run that grades this work (see G1).

AT FREEZE: **fails, correct reason.** `assert 0 != 0` — the probe file was written into
`scripts/`, `make gate-test` ran, reported `104 passed`, and exited **0**, so the recipe never ran
the probe. A real assertion failure at the criterion's own assertion (line 211), reached only after
the fixture wrote the probe successfully. Not a setup error. The probe was removed on the way out —
`git status` after the run shows no debris.

**On verifying the recursion guard.** The direct demonstration (setting
`AGENT_SESSION_GATE_TEST_INNER=1` by hand and observing the module skip) was **not run in this
session** — the harness blocks env-prefixed commands. It is not needed, because the implementation
proves it mechanically and more strongly: once the recipe globs, C2's inner `make gate-test`
collects this module, so **if the guard did not work, C2 could not terminate at all** — a passing
C2 is the proof. G1's "0 skipped" is the proof the guard is not over-applied to the outer run. Both
are recorded at the gate.

ORACLE EXISTS NOW: `make`, pytest, and process exit status. Nothing to build.

## Guards

(Pass today; must keep passing. Not criteria — they can't fail at freeze.)

- **G1:** `uv run pytest driver/test_*.py scripts/test_*.py -q` is green, with no test lost, newly
  skipped or newly failing. **Passed at freeze on `7309f61`: 111 collected, 111 passed, 0 skipped,
  0 failed.** After the work, the same command must still report 0 skipped — this is the guard that
  catches the recursion guard misfiring in an outer run.
- **G2:** `make check` exits 0. **Passed at freeze on `7309f61`.**
- **G3:** `make check` still runs every step it runs today — `driver-check`, `driver-test`,
  `park-test`, `skill-readonly`, `docs-check`, `assertion-lint`, `commit-lint`. Stated as "every
  step still reports" rather than as a count, because the cheap way to make a Makefile change green
  is to drop a step. **Passed at freeze on `7309f61`: all seven reported.**

## Amendments

(Append-only. Empty unless an amendment was made.)

_None._
