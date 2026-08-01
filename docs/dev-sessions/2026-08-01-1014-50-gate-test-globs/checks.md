# Frozen acceptance checks

**Source:** https://github.com/lmorchard/agent-sessions/issues/50
**Frozen at:** `9f20154` (2026-08-01)
**Check files — read-only from Phase 1 onward:**
- `scripts/test_gate_test_wiring.py`

The list is non-empty, so the real tamper mechanism applies — `git diff <freeze-sha> --
scripts/test_gate_test_wiring.py` must be empty, and it is re-runnable by a reviewer because the
freeze commit ships with the branch. No substitute verdict is needed or accepted here.

**Implementation files, for the record:** `Makefile` (the `gate-test` recipe). Disjoint from the
check file, so this run is *not* the "work must edit its own oracle" case — the ordinary whole-file
tamper diff is available and is what will be run.

## C1

CRITERION: WHEN `make gate-test` runs, THEN it SHALL collect every test file matching
`driver/test_*.py` and `scripts/test_*.py`.

CHECK: the collected count under `gate-test`'s own arguments equals the collected count under
the globs — `uv run pytest <gate-test args> --collect-only` vs
`uv run pytest driver/test_*.py scripts/test_*.py --collect-only`.
Stated as equality between two live measurements, never as a pinned number, per defect class 3:
the invariant is "the recipe runs everything that exists", and any literal total goes stale the next
time a test is added.

ORACLE EXISTS NOW: pytest and `--collect-only`. Nothing to build.

CHECK COMMAND: `uv run pytest
scripts/test_gate_test_wiring.py::test_gate_test_collects_every_glob_matched_test_file`

AT FREEZE: **fails**, at its own assertion, having taken both live measurements first —

```
AssertionError: `make gate-test` does not run the same tests as driver/test_*.py scripts/test_*.py.
  recipe under test: 'uv run --quiet pytest driver/test_gate.py scripts/test_docs_check.py
    scripts/test_run_progress.py scripts/test_commit_lint.py scripts/test_commit_lint_edges.py'
  collected by recipe: 104   collected by globs: 113
  MISSING from gate-test (9): [the 7 scripts/test_assertion_lint.py tests, plus this module's 2]
  EXTRA in gate-test (0): []
```

The correct reason: the recipe was read out of the `Makefile` and executed, both sides collected a
non-zero number, and the difference is exactly the orphaned file the issue is about plus the two
checks being frozen here. Not an import error, not a parse failure, not exit 5.

## C2

CRITERION: WHEN a new test file matching those globs is added, THEN `make gate-test` SHALL run it
with **no edit to the `Makefile`**.

CHECK: with a temporary failing test file placed in `scripts/`, `make gate-test` exits non-zero;
with it removed, exit 0. The fixture must remove the file on exit, including on failure.

This is the criterion that closes the class; C1 alone is satisfiable by appending one filename,
which fixes the instance and leaves the next one available.

CHECK COMMAND: `uv run pytest
scripts/test_gate_test_wiring.py::test_new_test_file_runs_under_gate_test_with_no_makefile_edit`

AT FREEZE: **fails**, at its own assertion, having really written the probe and really run the
recipe first —

```
AssertionError: `make gate-test` exited 0 with a failing test file at
test_zz_gate_wiring_probe_35722_8d84165a.py in place, so it never collected it.
Adding a test file must not require a Makefile edit.
  --- output ---
  104 passed in 1.71s
assert 0 != 0
```

The correct reason: the probe existed on disk, `make gate-test` ran to completion against it, and
the recipe simply never looked at it. The probe was removed by the `finally`; `ls scripts/`
confirmed no residue.

**Two strengthenings the check-author added, recorded because they are part of the frozen oracle.**
Both narrow what can satisfy C2; neither relaxes it.
- The first arm also asserts the probe's *filename appears in the recipe's output*. Without it, once
  the recipe globs, the inner run also executes C1, and *any* inner failure would satisfy a bare
  non-zero exit — the check would stop proving anything about the new file.
- The test asserts the `Makefile` is byte-identical before and after, which is the criterion's
  "with **no edit to the `Makefile`**" clause made mechanical rather than left to good behaviour.

## Guards

(Pass today; must keep passing. Not criteria — they can't fail at freeze.)

- **G1:** `uv run pytest driver/test_*.py scripts/test_*.py -q` — every test that passes today still
  passes, with no test lost, newly skipped or newly failing. Passed at freeze: exit 0, 111 collected,
  111 passed, 0 skipped, measured on the worktree before any implementation.
- **G2:** `make check` exits 0. Passed at freeze.
- **G3:** `make check` still runs every step it runs today — `driver-check`, `driver-test`,
  `park-test`, `skill-readonly`, `docs-check`, `assertion-lint`, `commit-lint`. Stated as "every step
  still reports" rather than as a count, because the cheap way to make a Makefile change green is to
  drop a step. Passed at freeze: 7/7 reported.

## Hazards named at freeze, not discovered mid-run

The spec asked for two of these to be settled here rather than found later. A third and fourth come
from Copilot's review of PR #56 — the previous, externally-killed run on this same issue, which Les
closed unmerged with the instruction that the replacement run should be expected to rediscover them.

1. **Recursion.** The check file lives in `scripts/` and therefore matches the glob the recipe will
   use. C2 must invoke `make gate-test` for real, and that inner invocation re-collects this very
   module — unbounded without a guard. Guarded by an environment variable set only on the inner
   invocation, under which this module's tests skip. The skips occur only inside the subprocess, so
   G1's outer run still reports 0 skipped; that is the signal that the guard is not over-applied.
   C1 needs no guard: it collects rather than runs, and collection imports the module without
   executing any test body.

2. **Cleanup / stray probe.** C2 writes a failing test file into the real `scripts/` directory. A
   killed run could leave it behind, and a stray failing probe would break `make check` for everyone
   until deleted by hand. Teardown is a `finally` around an unlink, so it survives assertion failure,
   error and `KeyboardInterrupt`. **The residual risk is real and is accepted, not closed:** a
   `SIGKILL` defeats `finally`. The spec's own CHECK wording requires a *failing* probe, so the
   safer passing-probe variant is not available without an amendment. The probe name is made
   distinctive so a survivor is greppable.

3. **Probe filename collisions** (Copilot, PR #56). A fixed probe filename lets two concurrent
   `make check` runs in one working tree race — one deleting the other's probe between the non-zero
   and zero arms. The probe name embeds the process id.

4. **Ambient environment** (Copilot, PR #56). Two sub-hazards, both about the subprocess honestly
   reflecting the recipe:
   - `PYTEST_ADDOPTS` must be *appended to*, never overwritten. A developer or CI with
     `PYTEST_ADDOPTS` already set would otherwise see this check fail for reasons unrelated to the
     Makefile wiring.
   - The recipe script extracted from `make -n` must run under `bash -e`. Plain `bash -c` returns
     only the *last* command's status, so if the recipe ever prints more than one line an early
     failure is masked and the check could pass against a broken recipe.

## Anti-restatement requirement

`gate-test`'s arguments must be **derived from the `Makefile` at run time** (via `make -n gate-test`),
never restated in the check. A check that hardcodes the recipe's argument list is asserting its own
copy, which is `findings.md` defect class 5 — a spelling check, not a test — and is the exact class
`assertion_lint` exists to detect. This is what makes C1 non-vacuous even where its two sides look
alike.

## Amendments

(Append-only. Empty unless an amendment was made.)

None.

## Tamper verdict

Recorded by the independent verifier — a fresh context given this file and the repo, and
deliberately not given `plan.md`, `notes.md`, or any account of why a failure might be acceptable.

**`clean` — by the real mechanism, not by substitute.** `Check files` is non-empty, so this is the
whole-file diff and a reviewer can re-run it:

- `git diff 9f20154 -- scripts/test_gate_test_wiring.py` → **empty**. Byte-identical to the freeze.
- `git diff 9f20154 --stat -- . ':!docs'` → the `Makefile` alone, which is the declared
  implementation file.
- This file's own diff is exactly one line — the `Frozen at` sha. **No CRITERION line, no CHECK
  command, and no guard command differs from the frozen version.** Amendments still `None`.

**Results, each by its own command:** C1 pass (1 collected, 1 passed, exit 0 — not exit 5) · C2 pass
(1 collected, 1 passed; no probe residue) · G1 pass (113 collected, 113 passed, 0 failed, **0
skipped**) · G2 pass (exit 0) · G3 pass (7/7, verified against the `check:` prerequisite list as well
as the output).

**Asked whether the diff could satisfy the checks without doing the work, the verifier said no**, and
gave the reason: both checks are behavioural end-to-end and neither asserts over text, so no rename
or reflow could move either side. It re-derived the discrimination independently — the pre-fix
argument list collects 104 against the globs' 113, a delta of exactly the 7 orphaned tests plus these
2 checks.

### A defect in G1's *wording*, found by the verifier and deliberately NOT fixed here

`pyproject.toml` already sets `addopts = "-q"`, so this manifest's extra `-q` makes G1's command
`-qq`, which suppresses the summary line entirely. **The command as frozen cannot itself print the
collected/passed/skipped numbers the guard is phrased to ask for.** The verifier obtained them by
running the same argument set without the redundant flag.

Two things follow, and the second is the point:

1. It changes no verdict. Exit status is 0 either way, at the freeze tree and at the implementation
   tree, so by `frozen-checks.md`'s four-cell test this is at most a clarification — never an
   amendment, and it costs the tier nothing.
2. **It is still not being edited mid-run.** This manifest is append-only, and rewriting a guard
   command in it is the same act whether the rewrite improves it or weakens it. The `-q` was
   introduced here when the manifest was written — the issue's own G1 has no `-q` — so the honest
   record is that the transcription added a flag, the guard passed anyway, and the fix belongs to
   whoever writes the next manifest rather than to this run's diff.
