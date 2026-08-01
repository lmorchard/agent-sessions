# gate-test runs every test file — Implementation Plan

**Goal:** make `make gate-test` run every Python test file that exists, rather than the five it
names, so that "a new test file is never run" stops being reachable.

**Source issue:** https://github.com/lmorchard/agent-sessions/issues/50 — **Tier:** `auto-ok`
(both criteria are counted / exit-status assertions with pytest as the oracle; the work lands in
`Makefile` and `scripts/`, both on `CLAUDE.md`'s drivable allowlist — not `driver/gate.py`, not
`skills/**`)

**Approach:** replace the hand-maintained file list in the `gate-test` recipe with the two shell
globs the criteria are written in terms of. Per the spec's Design decisions, appending the one
missing filename is explicitly rejected: the omission is not the defect, the census is.

**Criteria:** C1 the recipe collects everything the globs match · C2 a new test file runs with no
`Makefile` edit
(Full text + checks live in `checks.md`. Ids are assigned there and referenced here.)

---

## Phase 0: Freeze the acceptance checks — DONE

Frozen at `a06c74d`. `checks.md` written; `scripts/test_gate_test_wiring.py` authored by a
check-author subagent that was given the criteria but not the implementation approach.

**Files:**
- Created: `docs/dev-sessions/2026-08-01-0919-50-gate-test-glob/checks.md`
- Created: `scripts/test_gate_test_wiring.py` — the tests C1 and C2 name

**Verification — automated:**
- [x] C1's check fails for the expected reason — `assert 104 == 113`, a real assertion at the
      criterion's own assertion after `make -n` parsed and both collections exited 0
- [x] C2's check fails for the expected reason — `assert 0 != 0`; the probe was written into
      `scripts/`, `make gate-test` reported `104 passed` and exited 0
- [x] G1 passes: `uv run pytest driver/test_*.py scripts/test_*.py -q` — 111 collected, 111
      passed, 0 skipped at `7309f61` (before the check file existed)
- [x] G2 passes: `make check` exits 0 at `7309f61`
- [x] G3 passes: all seven steps reported at `7309f61`
- [x] Freeze commit made (`a06c74d`); sha recorded in `checks.md`

---

## Phase 1: Glob the `gate-test` recipe

The whole change, and it is one line plus its comment. There is exactly one slice here because the
work does not decompose: the recipe either names files or it does not, and both criteria turn on
the same edit.

**Advances:** C1, C2 — both, completely. Nothing remains for a later phase.

**Files:**
- Modify: `Makefile` — the `gate-test` recipe at line 52–53. Replace the five literal paths with
  `driver/test_*.py scripts/test_*.py`, and add a comment saying why a list was wrong and what the
  new cost is.

**Key changes:**

```make
# A glob, not a list. A list of test paths here is a census of a growing set, and
# this recipe already proved the failure mode: scripts/test_assertion_lint.py
# existed, passed, and went unrun under `make check` for as long as it existed --
# while the detector it tests is the mitigation for findings.md defect class 5.
# Globbing makes "a new test file is not run" unreachable rather than fixed once.
#
# Shell globs rather than $(wildcard): a glob that matches nothing reaches pytest
# as a literal pattern and errors loudly, where $(wildcard) would expand to nothing
# and let pytest fall back to pyproject's `testpaths` -- a different set, silently.
#
# Cost, so it is not a surprise: scripts/test_gate_test_wiring.py is matched by
# this glob and shells out to `make gate-test` twice, so this target now runs the
# suite about three times over. It is bounded -- the inner runs are marked
# AGENT_SESSION_GATE_TEST_INNER and skip that module -- and it is not optional:
# C1 requires the recipe to run every file matching the globs, and that file
# matches them.
gate-test:
	@uv run --quiet pytest driver/test_*.py scripts/test_*.py
```

**Verification — automated:**
- [ ] C1's check passes:
      `uv run pytest scripts/test_gate_test_wiring.py::test_gate_test_collects_every_globbed_test -q`
- [ ] C2's check passes:
      `uv run pytest scripts/test_gate_test_wiring.py::test_a_new_test_file_is_run_without_a_makefile_edit -q`
- [ ] G1 still passes: `uv run pytest driver/test_*.py scripts/test_*.py -q` — green, and
      **0 skipped** (this is also what proves the recursion guard is not over-applied to the
      outer run)
- [ ] G2: `make check` exits 0
- [ ] G3: `make check` still reports all seven steps — `driver-check`, `driver-test`, `park-test`,
      `skill-readonly`, `docs-check`, `assertion-lint`, `commit-lint`
- [ ] `scripts/test_assertion_lint.py` is observably now running under `make check` — the thing
      the issue was filed about
- [ ] No probe debris: `git status --short` shows no `scripts/test_zz_probe_delete_me.py`
- [ ] Tamper diff empty: `git diff a06c74d -- scripts/test_gate_test_wiring.py`

**Verification — manual:**
- None. Both criteria are mechanical; the tier is `auto-ok` for exactly that reason.

---

## Phase 2: Session notes

Write `notes.md` with the outcome, and record anything the run learned that outlives it.

**Advances:** no criterion — this is the session artifact `CLAUDE.md` requires, not scope. Called
out explicitly rather than folded into Phase 1 so that "every phase advances a criterion" stays a
real check with one honest exception rather than a fudged one.

**Files:**
- Modify: `docs/dev-sessions/2026-08-01-0919-50-gate-test-glob/notes.md`

**Verification — automated:**
- [ ] `make docs-check` passes (it is in `make check`, and these notes carry literal counts, which
      is the pattern its assertion-count detector looks at)

---

## Out of scope, per the spec

- **Changing what any test asserts.** A test that starts running and fails is a pre-existing break
  to report, not to fix here. `scripts/test_assertion_lint.py` is green today, so this is not
  expected to bite — but if it does, it is a report, not a repair.
- **Globbing `driver/test-*.sh`.** The bash suites are wired separately through `driver-test` and
  `park-test`.
