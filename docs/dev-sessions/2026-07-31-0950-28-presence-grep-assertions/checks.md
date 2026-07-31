# Frozen acceptance checks

**Source:** https://github.com/lmorchard/agent-sessions/issues/28
**Frozen at:** _(recorded in the follow-up commit)_
**Branch base:** `c46c8e2` (origin/main at setup)

**Check files — read-only from Phase 1 onward:**
- `scripts/test_assertion_lint.py`

C1 and C3 are **commands, not test files**, so for those two the tamper diff over `Check files`
is meaningless rather than satisfied, and the substitutes in `frozen-checks.md` ("When the
criteria are commands, not test files") apply. C2 alone has a frozen file.

**This run edits its own oracle, in a bounded way.** C1's work is to change assertions in
`driver/test-driver.sh` — a test suite. That file is *not* in `Check files` and is not frozen;
guard G1 is what holds it honest. The scoped invariant, per `frozen-checks.md`:

> No line in the diff to `driver/test-driver.sh` may reduce what the suite asserts — no assertion
> deleted, no expected value loosened, no case skipped. Sanctioned: converting a presence-grep
> assertion into a comment-excluded form that asserts the same fact.

## C1

CRITERION: No assertion in `driver/test-driver.sh` SHALL be satisfiable by the searched
literal appearing in a comment.
CHECK: `grep -cE '^[^#]*grep -q[EF]? .*"\$DRIVER"' driver/test-driver.sh` reports `0`.
AT FREEZE: **fails — reports `8`** (correct reason: the eight assertions are genuinely present,
at lines 213 244 245 255 260 267 272 337 — re-verified against this branch's base `c46c8e2`,
not taken from the issue).

## C2

CRITERION: GIVEN a bash fixture whose assertion is `grep -q 'literal' "$F"`, WHEN the detector
runs over it, THEN it SHALL report that line; AND GIVEN a fixture whose assertion compares
`grep -cE '^literal\(\)' "$F"` against an expected count, it SHALL NOT report it; AND GIVEN
`driver/test-park-state.sh` it SHALL report nothing.
CHECK: `uv run pytest scripts/test_assertion_lint.py` passes.
AT FREEZE: **fails — `ModuleNotFoundError: No module named 'assertion_lint'`, exit code 2**
(collection error; the module under test is the deliverable and genuinely does not exist).

**Stated plainly rather than glossed:** exit 2 is a *collection* error, so the seven assertions
in the file have not yet been observed to have teeth — `frozen-checks.md` warns that a check
failing on an import error "is not yet a check". Here the import error IS the criterion's
condition, which is why it is accepted; but the residual doubt is real and is discharged two ways
at verification rather than asserted away:

1. exit **2**, not **5** — the file collected, so this is distinguishable from `no tests ran`;
2. after implementation the verifier must record the **passed count** (expected: 7 passed), and
   each of C2's three conjuncts must be individually named in its report. A count of 7 is what
   shows the assertions ran rather than the module merely importing.

The test file was authored by a **check-author subagent** given the criterion and the house
pattern but NOT the implementation approach, per `frozen-checks.md`. It defines the interface
(`ROOT`, `failures`, `scan_file(path)`, `lint_files()`); the implementer conforms to it.

## C3

CRITERION: WHEN a presence-grep assertion exists in a linted file, THEN `make check` SHALL
fail.
CHECK (mutation test, run and recorded at freeze): append
`if grep -q 'STATE_DIR' "$DRIVER"; then :; fi` to a linted bash suite, run `make check`, observe a
non-zero exit; revert and observe `all checks passed`.
AT FREEZE: **fails — mutation appended to `driver/test-driver.sh` (the linted bash suite that
defines `$DRIVER`), `make check` exited `0` and printed `all checks passed`.** The criterion
demands non-zero, so the mutation changed nothing: demonstrated. Reverted with
`git checkout -- driver/test-driver.sh`; `git diff --stat` empty afterwards.

*Why `test-driver.sh` and not `test-park-state.sh`:* the latter is itself a frozen acceptance
file for issue #5 and is read-only (`driver/test-park-state.sh:7-8`). It is also C2's live
negative fixture. Mutating it would be editing another run's oracle.

## Guards

(Pass today; must keep passing. Not criteria — they can't fail at freeze.)

- G1: `bash driver/test-driver.sh` reports `0 failed`, with the assertion count **not below 64**
  — a floor, not an equality.
  AT FREEZE: **passes — `88 passed, 0 failed`.** 88 ≥ 64, so the floor holds with headroom; the
  issue recorded 64 on 2026-07-29 and the suite has grown since. **The post-implementation floor
  is 88, not 64** — this run must not shrink the suite it inherited, and 64 would let it drop 24
  assertions unnoticed.
  RUN VIA: `make driver-test`, whose recipe is literally `@bash driver/test-driver.sh`
  (`Makefile:47`). The bare command is unavailable to this sandboxed run; the wrapper is a
  superset (it runs `gate-test` first), not a substitute. Stated because a reader must be able to
  tell an unavailable mechanism from a satisfied one.
  **Load-bearing:** C1's cheapest cheat is to *delete* the eight assertions instead of
  strengthening them, which leaves C1 green and the suite green. Only this guard notices.
- G2: `make check` reports `all checks passed` before C3's mutation and again after reverting it.
  AT FREEZE: **passes — `all checks passed`**, observed both before the mutation and after the
  revert.
- G3: `python3 scripts/docs_check.py` exits 0 — no documentation rot.
  AT FREEZE: **passes — exit 0**, `docs-check: links resolve, tables well-formed, counts match`
  (`no assertion-count claims found to check; suite reports 88`).

## Amendments

(Append-only. Empty unless an amendment was made.)

_None._

## Tamper verdict

_(recorded at the end of execute and again in pr)_
