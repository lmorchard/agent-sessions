# Frozen acceptance checks

**Source:** https://github.com/lmorchard/agent-sessions/issues/32
**Frozen at:** `53b4a93` (2026-07-31)
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
  reported **79 passed, 0 failed** on `origin/main` (`39d4a75` tree, measured 2026-07-31).
- **G4:** `make driver-check` — the driver still has no executable merge path.
  Status at freeze: recorded in `notes.md`.

## Amendments

(Append-only.)

- **CLARIFICATION, not an amendment (2026-07-31).** G3's baseline note recorded the `origin/main`
  tree as `39a4d75`; the actual commit is `39d4a75`. Caught by the independent verifier, which
  checked the sha existed instead of taking it on trust.
  **Why a clarification:** the sha is provenance for where the baseline was measured, not part of
  what G3 asserts — G3 asserts *79 passed, 0 failed, nothing lost*. Applying
  `frozen-checks.md`'s mechanical test: the old and new wording produce the same verdict at the
  freeze commit AND against the current implementation, because neither tree's assertion count
  depends on how the baseline commit is spelled. Both cells "verdict same" → clarification. No
  tier change.

## Tamper verdict — recorded by the independent verifier (2026-07-31)

`git diff 53b4a93 -- driver/test-driver.sh` is **NOT empty**, and the reason is disclosed rather
than explained away: the run appended a separately fenced `#32 coda: NOT FROZEN` block covering a
second latent defect that surfaced *after* the freeze had closed.

**Verdict: clean under the stated invariant.** The invariant, as `frozen-checks.md` requires it be
stated — over what the checks assert, not as a whitelist of allowed line forms:

> No line in the diff may change what any frozen check asserts — no test body, assertion, expected
> value, fixture, helper, `skip`/`xfail` marker, or signature belonging to C1, C2 or G1.

The verifier's finding, on a fresh context with only this manifest and the repo: **no.** The diff
is a single purely-additive hunk inserted after the frozen section's closing `rm -rf "$C32_TMP"`;
`grep '^-'` over it yields zero content-removal lines, and the C1/C2/G1 code — `C32_SHA`,
`C32_BODY`, the `classify_pr_body`/`say`/`log` sed-extraction, the C1 `check` calls, the G1 `case`
block, and C2's stub and outcome-enum assertion — is byte-for-byte identical between `53b4a93` and
HEAD. Same result for `origin/main` → `53b4a93`: purely additive, nothing removed, so the
baseline's 79 assertions are byte-identical in HEAD's copy of the file.

**Teeth:** the verifier states the diff could not have made any frozen check pass without the work
being done — it does not touch the C1/C2/G1 code, those assertions are literal-value equality
checks against the *shipped* `classify_pr_body` extracted by `sed`, and there is no fixture, mock
or skip marker in the diff that could satisfy them vacuously. Suite: **88 passed, 0 failed**.

## Tamper verdict

(Recorded by the independent verifier at the end of the run.)
