# Frozen acceptance checks — issue #9 (gate parser extraction)

Frozen at: (recorded in the follow-up commit — a commit cannot contain its own hash)
Issue: https://github.com/lmorchard/agent-sessions/issues/9
Tier: `needs-review` — two legs: the issue's own hand-run hazard, and dependency addition (pytest + uv).

Decisions in force: **D1** parsing *and* classification move to Python. **D2** pytest managed by `uv`;
`driver/gate.py` itself stays stdlib-only so the driver remains portable.

## C1 — the parser exists and classifies ci-stale correctly

CRITERION: WHEN given a PR body on stdin and a head sha, the gate parser SHALL be a Python module
emitting normalised JSON containing the classified outcome — for a gate block graded at `0d08b2d`
with head `e8f03389`, it SHALL emit outcome `ci-stale`.

CHECK: `printf '%s' "$BODY" | python3 driver/gate.py classify --head-sha e8f03389 | python3 -c "import json,sys; assert json.load(sys.stdin)['outcome']=='ci-stale'"`

Observed at freeze: **FAILS** — `driver/gate.py`: No such file or directory.
Expected value verified against the *shipped bash* classifier on the identical fixture, which
returns `ci-stale`. Not assumed.

## C2 — no bash file defines the parsers any more

CRITERION: Gate-block parsing and outcome classification SHALL live only in the Python module — no
`.sh` file in `driver/` SHALL define `classify_outcome`, `gate_field`, or the gate-marker awk
extractor.

CHECK: `grep -cE '^classify_outcome\(\)|^gate_field\(\)|^extract_gate\(\)' driver/agent-session-driver.sh driver/test-driver.sh` reports `0` for both.

Observed at freeze: **FAILS** — 3 in `agent-session-driver.sh`, 3 in `test-driver.sh`.

## C3 — one implementation site for the verdict vocabulary  *(AMENDED — see A1)*

CRITERION: `gate-eligible` / `gate-human` / `no-gate` / `ci-stale` SHALL be *produced* by exactly one
source file. Comments and test expectations are inert.

CHECK (amended): `grep -nE 'gate-eligible|gate-human' driver/agent-session-driver.sh | grep -v '^[0-9]*:#' | wc -l` → `0`.

Original check, superseded: `grep -rlE 'gate-eligible' driver/ | grep -v '^driver/gate.py$' | wc -l` → `0`.
It could not distinguish an implementation from a mention. **Amended, not clarified** — see A1 for
the both-trees verdict table and why the intent-based read was refused.

Observed at freeze: **FAILS** — the driver's `classify_outcome` genuinely produced the vocabulary,
under both wordings.

## C4 — the tests import the module rather than restating it

CRITERION: The Python test file SHALL contain no definition of parsing or classification logic, and
its ci-stale case SHALL be produced by the imported module.

CHECK, both parts: `uv run pytest driver/test_gate.py -k stale -q` passes
AND `grep -cE '^def (classify|gate_field|extract_gate|tier_of|budget_reclass)' driver/test_gate.py` → `0`.

Observed at freeze: **FAILS** — no `.py` file exists under `driver/`.

## C5 — the parser stays stdlib-only (revised by D2)

CRITERION: `driver/gate.py` SHALL import only the standard library, so the driver remains portable
even though its *tests* use pytest.

CHECK: `python3 -I -S -c "import sys; sys.path.insert(0,'driver'); import gate"` exits 0.
(`-I -S` sees no site-packages, so a third-party import fails closed.)

Observed at freeze: **FAILS** — module does not exist.

## C6 — the divergence becomes unrepresentable (the point of the issue)

CRITERION: GIVEN the same gate block and head sha, the driver's classification and the test suite's
classification SHALL be produced by the same code path, such that no input can make them disagree.

CHECK: `bash driver/test-driver.sh` passes AND `grep -c 'classify_outcome()' driver/test-driver.sh` → `0`.

Observed at freeze: **FAILS** — verified they *do* disagree today. Same gate block
(`ci: 2/2 pass @ 0d08b2d`), same head (`e8f03389abcdef`):
shipped driver → `ci-stale`; test-file copy → `gate-eligible`.

## Guards (must PASS now and after)

- **G1.** `bash driver/test-driver.sh` → `0 failed`, count not below **47**.
- **G2.** `bash -n driver/agent-session-driver.sh` exits 0.
- **G3.** `make driver-check` → no executable merge path.
- **G4.** `make skill-readonly` → the three `$SKILL_DIR` deny rules survive.
- **G5.** `make dry-run REPO=lmorchard/agent-sessions BOARD=lmorchard/9` still reports
  `eligible: 3` — the end-to-end selection path is unchanged by the refactor.

Observed at freeze: G1 47 passed/0 failed · G2 syntax OK · G3 pass · G4 pass · G5 `eligible: 3`.

## Mutation test (the guard on the guards)

Narrowing `gate.py`'s ci-sha regex from `{7,40}` to `{40}` MUST make a **named** pytest case fail.
Today the equivalent mutation of the *driver's* regex leaves `driver-test` green — that is the
defect being fixed, so this mutation is the evidence the fix worked.

## Amendments

(Append-only. Empty unless an amendment was made.)

### A1 — C3, amended 2026-07-28. Human-confirmed by Les.

**Criterion (unchanged):** the verdict vocabulary SHALL have exactly one *implementation* site.

**Old check:**
```
grep -rlE 'gate-eligible' driver/ | grep -v '^driver/gate.py$' | wc -l   → 0
```

**New check:**
```
grep -nE 'gate-eligible|gate-human' driver/agent-session-driver.sh | grep -v '^[0-9]*:#' | wc -l   → 0
```
i.e. **no file other than `driver/gate.py` may *produce* a verdict value. Comments and test
expectations are inert.**

**Why the old check failed to test its own criterion.** After the extraction, the only occurrence of
`gate-eligible` in the driver is **inside a comment** — the explanatory note about the divergence
being fixed. The other five live in `test-driver.sh` as **expected values in assertions**, which is
what a test asserting the parser's output is supposed to look like. Zero code sites outside
`gate.py` produce a verdict. `grep -rl` cannot distinguish an implementation from a mention, so it
graded the wrong thing.

This is the **inert-content false positive** — the same trap `findings.md` documents for tamper
rules and that the `skill-readonly` guard fell into twice. **Third instance in this project**, and
written a few hours after re-reading the warning. Recorded because that recurrence is the finding,
not the check.

**Classified as an AMENDMENT, not a clarification**, under the policy adopted 2026-07-27. Verified by
running both wordings against both trees rather than reasoning about intent:

| | at the freeze commit | against the shipped implementation |
|---|---|---|
| **original** C3 | fails | **fails** |
| **amended** C3 | fails | **passes** |

The verdict changes against the implementation, which is the amendment signature. *"The check never
matched its own intent"* was the intuitive read and is deliberately **not** sufficient — it is the
same reasoning #668's run used to publish `amendments: none` and reach
`eligible-for-auto-merge`, and it is a story always available to whoever wrote the check. The
implementer is that whoever.

**Tier consequence:** the amendment path mandates a downgrade to `needs-review`. Issue #9 was
**already `needs-review`** on two independent legs (its own hand-run hazard; dependency addition),
so there is no autonomy left to forfeit. The downgrade is a no-op here — stated rather than claimed
as compliance.

**Adjudication note:** this is the first live exercise of the both-trees policy, and it caught the
author's own frozen check. Taken as an amendment deliberately, with the cost at zero, rather than
carving the policy's first exception in the author's own favour.
