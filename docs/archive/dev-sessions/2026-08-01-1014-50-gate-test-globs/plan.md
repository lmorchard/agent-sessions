# gate-test: glob, don't enumerate — Implementation Plan

**Goal:** make `make gate-test` collect every Python test file that exists under `driver/` and
`scripts/`, so that adding one cannot silently fail to run it.

**Source issue:** https://github.com/lmorchard/agent-sessions/issues/50 — **Tier:** `auto-ok`
(every criterion is a count or exit-status assertion with pytest as the oracle; the work lands in
`Makefile` and `scripts/`, both on CLAUDE.md's drivable allowlist — not `driver/gate.py`, not
`skills/**`).

**Approach:** replace the `gate-test` recipe's hand-maintained list of five literal file paths with
shell globs over `driver/test_*.py` and `scripts/test_*.py`. Settled at intake: the omission is not
the defect, the *census* is — a hand-maintained inventory of a growing set is the same staleness
shape that produced two wrong assertion counts in opposite directions. Appending one filename fixes
the instance and leaves the mechanism, which is why C2 is written so that appending cannot pass.

**Criteria:** C1 the recipe collects exactly what the globs collect · C2 a newly added test file runs
with no `Makefile` edit.
Full text and checks live in `checks.md`; ids are assigned there.

---

## Phase 0: Freeze the acceptance checks — **DONE**

Written before any implementation, per `references/frozen-checks.md`.

**Files:**
- Created: `docs/dev-sessions/2026-08-01-1014-50-gate-test-globs/checks.md` — criteria copied
  verbatim from the issue, ids assigned, four hazards named
- Created: `scripts/test_gate_test_wiring.py` — the tests C1 and C2 name. **Read-only from Phase 1
  onward.**

**Verification — automated:**
- [x] C1's check runs and fails for the expected reason — `104` collected by the recipe vs `113` by
      the globs, both measured live, difference exactly the orphaned file plus this module
- [x] C2's check runs and fails for the expected reason — `assert 0 != 0`, reached with the probe
      really on disk and the recipe having really run past it
- [x] G1 passes at freeze — `uv run pytest driver/test_*.py scripts/test_*.py -q`, exit 0, 0 skipped
- [x] G2 passes at freeze — `make check` exits 0
- [x] G3 passes at freeze — all seven steps report
- [x] Freeze commit made: `9f20154`. Sha recorded in `checks.md` in the follow-up commit.

---

## Phase 1: Glob the `gate-test` recipe

The whole implementation. One recipe line in the `Makefile`, plus the comment block explaining why a
list was wrong — this repo's Makefile documents the *reason* beside each guard, and a bare glob with
no rationale invites someone to re-pin the list later.

**Advances:** C1, C2 — fully. There is no later phase; the work is one line and its rationale.

**Files:**
- Modify: `Makefile` — the `gate-test` recipe: five literal paths → `driver/test_*.py
  scripts/test_*.py`, preceded by a comment block.
- Test: none of its own. The frozen acceptance tests in `scripts/test_gate_test_wiring.py` already
  cover this slice end-to-end and are **read-only from here on**. A unit test would be a third copy
  of the same assertion.

**Key change:**

```makefile
gate-test:
	@uv run --quiet pytest driver/test_*.py scripts/test_*.py
```

**Why shell globs, and not the two alternatives:**

- **Not `$(wildcard …)`.** A `wildcard` matching nothing expands to *nothing*, leaving a bare
  `pytest` that falls back to `pyproject.toml`'s `testpaths` — a different set of tests, collected
  silently. A shell glob matching nothing is passed through literally and pytest errors on it. Loud
  beats silent for a recipe whose entire job is "don't quietly run less than you should."
- **Not a bare `pytest`** leaning on `testpaths = ["driver", "scripts"]`. Tempting, because it has no
  census at all and would make C1 a comparison between two genuinely independent mechanisms rather
  than two spellings of one. Rejected for two reasons: it moves the wiring into `pyproject.toml`,
  which is *not* on CLAUDE.md's drivable allowlist and is the dependency file besides; and it makes
  the recipe's behaviour invisible at the point a reader looks for it. The cost is that C1's two
  sides end up looking alike — see the honest note in the PR body, and note that C1 is still derived
  from the `Makefile` rather than restated, so it fires on a re-pinned list, an added `--ignore`, or
  a changed `python_files`.

**Verification — automated:** (each ticked from the output of that exact command, read)
- [x] C1's check passes: `uv run pytest
      scripts/test_gate_test_wiring.py::test_gate_test_collects_every_glob_matched_test_file`
      — `1 passed, 1 deselected`
- [x] C2's check passes: `uv run pytest
      scripts/test_gate_test_wiring.py::test_new_test_file_runs_under_gate_test_with_no_makefile_edit`
      — `1 passed, 1 deselected`, and `ls scripts/` showed no probe residue afterwards
- [x] G1 still passes: `uv run pytest driver/test_*.py scripts/test_*.py -q` — **113 passed, 0
      failed, 0 skipped**. Nothing lost, nothing newly skipped, nothing newly failing: 111 at freeze
      plus this run's 2 new checks. The **0 skipped** is the load-bearing half — a non-zero skip
      count in the *outer* run would mean the recursion guard had been over-applied.
- [x] G2 still passes: `make check` exits 0 — `all checks passed`
- [x] G3 still passes: `make check` reported all seven steps — `driver-check`, `driver-test`
      (113 + 112), `park-test` (28), `skill-readonly`, `docs-check`, `assertion-lint`, `commit-lint`
- [x] `scripts/test_assertion_lint.py`'s tests actually run under `make gate-test` — confirmed **by
      name**, all seven node ids collected, not merely by a total going up
- [x] Tamper diff empty: `git diff 9f20154 -- scripts/test_gate_test_wiring.py` produced no output.
      `git diff 9f20154 -- …/checks.md` shows only the sanctioned `Frozen at` write; no CRITERION or
      CHECK line differs.

**Verification — manual:**
- None. Both criteria are mechanical; the tier is `auto-ok` precisely because nothing here needs a
  human to grade it. The merge gate is still a stop.

---

## Expected side effects, so they are not mistaken for defects

- **`make gate-test` gets slower.** It now runs nine more tests, and C2 spawns two full `make
  gate-test` subprocesses, each of which also runs C1, which spawns two `--collect-only` runs.
  Bounded at depth 2 — collection imports modules without executing test bodies, so it cannot
  recurse further.
- **`driver-test` depends on `gate-test`**, so `make check` inherits the same cost.
- **A killed run can leave a probe file in `scripts/`.** Named
  `test_zz_gate_wiring_probe_<pid>_<hex>.py` and greppable; the risk is recorded in `checks.md`
  rather than closed, because the frozen CHECK wording requires a *failing* probe.
