# Frozen acceptance checks

**Source:** https://github.com/lmorchard/agent-sessions/issues/32
**Frozen at:** (recorded in the follow-up commit)
**Check files — read-only from Phase 1 onward:**
- `driver/test-driver.sh` (the `#32` section only; the rest of the file is prior issues'
  frozen checks and is equally read-only)

**Implementation file, disjoint from the above:** `driver/agent-session-driver.sh`.

**Note on the check-author subagent.** `frozen-checks.md` step 2 prescribes dispatching a
check-author subagent that has not seen the implementation plan. This run's operating
instructions prohibit spawning subagents, so the isolation was obtained by *ordering* instead:
these checks were authored and their failures observed **before** any implementation approach
was chosen or `plan.md` was written. Stated rather than skipped silently — the property the
subagent buys is "the check was not shaped by the implementation", and ordering buys the same
property with a weaker guarantee (one context rather than two).

## C1

CRITERION: WHEN the classifier emits a warning, the driver SHALL record the gate's outcome and
reason, and SHALL NOT record any part of the warning text in the `outcome` field.

CHECK: `make driver-test` — the `#32 C1` assertions. A case invoking the shipped
`classify_pr_body`, extracted out of `driver/agent-session-driver.sh` by the
`driver/test-park-state.sh` `sed`-extraction pattern (which runs the shipped text rather than a
copy), against a gate block whose `ci` row is `not yet graded` and a non-empty head sha, then
asserting `outcome == "gate-eligible"` and `reason == "all rows satisfied"`.

**Reading of "asserting `outcome`":** the assertion is taken over the function's own documented
contract — its comment says *"Prints `outcome<TAB>reason`"*, so the check reads its **stdout**,
as both call sites do, and discards stderr. This is the fix-agnostic reading: it pins no
particular repair, and a repair that leaves the warning on stdout still leaves the function
violating the contract it documents, which is the defect.

AT FREEZE: fails — see the recorded output in `notes.md`. Expected symptom: `outcome` holds the
warning text and `reason` is empty, matching the shipped `runs.jsonl` row for decafclaw #657.

## C2

CRITERION: WHEN `--classify-only` runs against a PR whose gate triggers a warning, THEN the row
it appends to `runs.jsonl` SHALL carry a valid outcome.

CHECK: `make driver-test` — the `#32 C2` assertions. A case using the offline `gh`-stub pattern
(`make_stubs` / `run_driver` in `driver/test-park-state.sh`) to serve a PR body with an
unparseable `ci` sha, invoking the shipped driver with `--classify-only <n>` against a temp
`--state-dir`, then asserting the appended row's `.outcome` is one of the known outcome values
(`gate-eligible|gate-human|ci-stale|incomplete|parked|failed|no-gate|budget-exhausted`).

AT FREEZE: fails — recorded in `notes.md`. The spec marked this **UNRUN as a test node**; the
freeze runs it and records the observed failure rather than inheriting the note. It is a
separate criterion from C1 because it is a **second call site**, and a fix at one and not the
other is `docs/findings.md` class 1's "fixed the cost field, never generalised" pattern.

## Guards

(Pass today; must keep passing. Not criteria — they can't fail at freeze.)

- **G1:** the warning is still visible to the operator after the fix — the same invocation as C1
  still emits the warning text somewhere the operator sees (stderr, or the run report).
  **CHECK:** the `#32 G1` assertion — C1's invocation with stdout and stderr **combined** still
  contains `ci row carries no parseable sha`. Load-bearing: the cheapest way to green C1 is to
  delete the `say` line, which trades a corrupted record for a missing one.
  Status at freeze: recorded in `notes.md`.
- **G2:** `driver/gate.py` is unchanged by this work. Load-bearing for the tier — `gate.py` is
  risk-gated in `CLAUDE.md`, so a fix reaching into it voids the `auto-ok`.
  **CHECK:** `git diff --name-only origin/main..HEAD` contains no `driver/gate.py`.
  Status at freeze: recorded in `notes.md`.
- **G3:** `make driver-test` — no assertion lost, newly skipped, or newly failing. Invariant,
  not a count. **Baseline recorded at freeze so "lost" is checkable:** `driver/test-driver.sh`
  reported **79 passed, 0 failed** on `origin/main` (39a4d75 tree, measured 2026-07-31).
- **G4:** `make driver-check` — the driver still has no executable merge path.
  Status at freeze: recorded in `notes.md`.

## Amendments

(Append-only. Empty.)

## Tamper verdict

(Recorded by the independent verifier at the end of the run.)
