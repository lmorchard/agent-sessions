# Presence-grep assertions pass on a comment: fix the eight in test-driver.sh and add a detector

**Source:** https://github.com/lmorchard/agent-sessions/issues/28

_Body captured verbatim from the issue; the `agent-session:spec` marker line is stripped._

## Goal

`driver/test-driver.sh` contains **eight assertions of the form `grep -q '<literal>' "$DRIVER"`** —
verified 2026-07-29 at lines 213, 244, 245, 255, 260, 267, 272 and 337. Each passes if the string
appears anywhere in the driver, **including inside a comment**. `docs/findings.md` (defect class 5)
calls this *"a spelling check, not a test"* and records it as still shipping;
`driver/test-driver.sh:177-179` and `driver/test-park-state.sh:19` both carry the warning **in a
comment** while the assertions remain.

Fix the eight, and add a detector so the class cannot come back. The detector is the load-bearing
half: `findings.md` has three data points for *"knowing the hazard demonstrably does not prevent
it"*, and this warning has now sat in two comments for two days next to the thing it warns about.

**Split out of #12**, which collected the evidence in its table but is `needs-review` for reasons
that do not apply here — #12's deliverable is `skills/**`, while this touches only `driver/`,
`scripts/` and `Makefile`.

**The class caught the author of this issue, during intake.** The first probe run,
`grep -cE 'grep -q[EF]? .*"\$DRIVER"' driver/test-driver.sh`, returned **9** — it matched the
*comment* at `:177` that describes the trap. Adding the `^[^#]*` exclusion from `Makefile:75`
returns 8. That is the inert-content false positive occurring inside the measurement of itself,
which is why C1 below is written with the exclusion rather than without it.

## Verifiable acceptance criteria

- CRITERION C1: No assertion in `driver/test-driver.sh` SHALL be satisfiable by the searched
  literal appearing in a comment.
  CHECK: `grep -cE '^[^#]*grep -q[EF]? .*"\$DRIVER"' driver/test-driver.sh` reports `0`.
  DEMONSTRATED FAILING 2026-07-29: reports **8**, at lines 213 244 245 255 260 267 272 337.
  Precedent for the fix shape, not a new invention: two assertions were already converted this way
  and `driver/test-driver.sh:177-179` records why.

- CRITERION C2: GIVEN a bash fixture whose assertion is `grep -q 'literal' "$F"`, WHEN the detector
  runs over it, THEN it SHALL report that line; AND GIVEN a fixture whose assertion compares
  `grep -cE '^literal\(\)' "$F"` against an expected count, it SHALL NOT report it; AND GIVEN
  `driver/test-park-state.sh` it SHALL report nothing.
  CHECK: `uv run pytest scripts/test_assertion_lint.py` passes.
  The third conjunct is a **real negative fixture that already exists** — verified 2026-07-29,
  `grep -cE '^[^#]*grep -q' driver/test-park-state.sh` → **0**, against **8** for
  `test-driver.sh`. It is worth more than a synthetic clean fixture because a detector that flags
  everything passes the synthetic one.
  ORACLE EXISTS NOW: `scripts/test_docs_check.py:19-36` is the pattern to copy — it *imports* the
  module under test, builds throwaway trees in pytest's `tmp_path`, and monkeypatches `ROOT`; it is
  run by `Makefile:50` (`uv run --quiet pytest driver/test_gate.py scripts/test_docs_check.py`).
  The criterion names the assertions the test must make, so the check grades content rather than
  existence — `references/acceptance-criteria.md`'s *"the work IS the oracle"* hard case.
  DEMONSTRATED FAILING 2026-07-29: no such detector exists, and `make check` exits 0
  (`all checks passed`) with all eight assertions present. **That** is the demonstration; `no tests
  ran` is deliberately not offered, per `acceptance-criteria.md`'s named-but-absent row.

- CRITERION C3: WHEN a presence-grep assertion exists in a linted file, THEN `make check` SHALL
  fail.
  CHECK (mutation test, run and recorded at freeze): append
  `if grep -q 'STATE_DIR' "$DRIVER"; then :; fi` to a linted bash suite, run `make check`, observe a
  non-zero exit; revert and observe `all checks passed`.
  DEMONSTRATED FAILING 2026-07-29: `make check` exits 0 today with eight such assertions present, so
  the mutation changes nothing.
  This is the criterion that cannot pass unless the detector both exists *and* is wired in. A
  `make -n check | grep` would be a presence-grep on a Makefile — the very shape this issue
  indicts — so it is not used.

## Regression guards

Guards pass now and must keep passing. All three were run 2026-07-29.

- GUARD G1: `bash driver/test-driver.sh` reports `0 failed`, with the assertion count **not below
  64** — a floor, not an equality, per `findings.md` defect class 3 (brittle absolutes).
  RAN: `64 passed, 0 failed`.
  **Load-bearing, and the reason it is listed first:** C1's cheapest cheat is to *delete* the eight
  assertions instead of strengthening them, which leaves C1 green and the suite green. Only this
  guard notices.
- GUARD G2: `make check` reports `all checks passed` before C3's mutation and again after reverting
  it. RAN: `all checks passed`.
- GUARD G3: `python3 scripts/docs_check.py` exits 0 — no documentation rot. RAN:
  `docs-check: links resolve, tables well-formed, counts match` (it currently reports
  `no assertion-count claims found to check; suite reports 64`).

## Tier: auto-ok

Both triggers were checked and neither fires.

**Trigger 1 does not fire.** C1 and C3 are commands with observed failing values recorded above; C2
is a pytest suite whose harness exists today and whose assertions the criterion names, so it grades
content rather than existence. No criterion rests on human judgment. Neither of the two tests in
`acceptance-criteria.md` is failed: every oracle exists now, and C1's satisfiable-without-the-work
route (delete the assertions) is closed by G1.

**Trigger 2 does not fire.** Paths touched: `driver/test-driver.sh`, `scripts/`, `Makefile` — all
three named in `CLAUDE.md`'s drivable allowlist. **Not** `driver/gate.py`; **not** `skills/**`. No
auth, secrets, data migration or deletion, deploy/infra/CI config, or dependency change: pytest and
`uv` are already dev dependencies (`pyproject.toml`; `Makefile:50`), so the detector's test adds
none.

**The narrow-oracle reading is what makes this drivable, and it is explicit rather than inferred.**
`CLAUDE.md` says gated means *"the code decides whether **this run's own work** is acceptable to
merge"* — the outcome classifier and nothing else — and names *"a future check-linter, however
detector-shaped"* as drivable alongside `scripts/docs_check.py`.

**Residual risk, named rather than gated away** — it is the same trade `CLAUDE.md` already accepts
for `docs_check.py`. A run that edits `driver/test-driver.sh` *and* authors the detector in one
change could shape the detector to pass whatever it left behind, with `make check` still green. Two
partial mitigations are built into the criteria rather than asserted: C1's check is a fixed command
frozen in `checks.md`, not code the implementer authors; and C3's mutation test requires a seeded
violation to actually turn `make check` red. Neither closes it completely, and a human is at the
merge gate.

## Design decisions

- **Decision: the detector's scope is `driver/test-*.sh` only — the Makefile is excluded.**
  - **Why:** the line is *file scope*, which is mechanical, rather than a semantic judgment about
    what a grep means. It covers every live instance. And `Makefile:71`'s `grep -qF` presence-greps
    are **legitimate**: `skill-readonly` asserts that a deny rule is literally present in the
    driver, so presence *is* the property being tested — unlike a test suite, where a presence-grep
    stands in for behaviour. Flagging it would be a false positive, and false positives train the
    operator to wave the mechanism through (`findings.md`).
  - **Rejected:** linting the Makefile too. That needs a semantic rule separating "presence is the
    property" from "presence stands in for behaviour", which is the same precision problem that got
    #12's option 2 declined. Widening the scope is a separate call for a human, not a drift to
    discover in a diff.

- **Decision: fix the eight *and* build the detector in one issue, not two.**
  - **Why:** they share one question — what counts as a presence-grep assertion — and
    `findings.md`'s counter-pressure on splitting is to *"split only to the granularity where each
    piece has its own question, or you ratify the same decision twice."* Fixing the eight without a
    detector also leaves the recurrence unaddressed, which is the point.
  - **Rejected:** a fix-only issue (the class recurs; three data points say the comment warning does
    not prevent it) and a detector-only issue (it would land red on eight live instances).

- **Decision: C3 is a mutation test rather than a wiring grep.**
  - **Why:** the honest question is *"does a violation turn `make check` red?"*, and only running it
    answers that. `findings.md`: *"'I wrote a guard' is not evidence"* — a guard is decoration until
    you mutate the thing it guards and watch it fail.
  - **Rejected:** `make -n check | grep -c assertion_lint` — a presence-grep on a Makefile, i.e. the
    defect this issue exists to remove, used as its own acceptance check.

## What we're NOT doing

- **Linting the `Makefile`'s guard recipes.** See the first design decision.
- **A general check-linter over `checks.md` manifests.** That is #12's option 2, and it was declined
  there on measured data: its headline rule would flag all five distinct grep commands in this
  repo's three frozen manifests, four of which were correct.
- **Touching `driver/gate.py`.** Not needed, and it is the one gated path in `driver/`.
- **Fixing `driver/test-park-state.sh`.** Nothing to fix — measured 2026-07-29, it has **zero**
  presence-grep assertions. It is in the detector's scope as C2's negative fixture, not as work.
  Recorded so a green result there is not mistaken for a skipped file.
