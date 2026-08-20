# Frozen acceptance checks

**Source:** https://github.com/lmorchard/agent-sessions/issues/5
**Frozen at:** `29968c9` (2026-07-29) — **re-anchored** after a rebase onto a moved `origin/main`.
The original freeze commit was `4c46753`; the rebase rewrote it. The baseline is unchanged in
substance and this is provable rather than asserted: `driver/test-park-state.sh` has blob hash
`d8b0855` in `4c46753`, in `29968c9`, and in the working tree. Re-anchoring on rebase is the
sanctioned write named in `references/frozen-checks.md`.
**Tier:** `auto-ok` (issue body is authoritative; the `auto-ok` label agrees)

**Check files — read-only from Phase 1 onward:**
- `driver/test-park-state.sh`

Criteria and checks are copied verbatim from the issue body's **"Criteria after D2"** section
(decision D2, 2026-07-29), which supersedes the earlier C1/C2/C3 there.

**Not wired into `make check` at freeze, deliberately.** G1 is "`make check` green" and must pass
*at* the freeze; wiring a failing check file into it would break that guard before any work started.
The last implementation phase wires it, and G1 then covers it for good.

**Authored inline rather than by a check-author subagent.** The skill prescribes a subagent that has
not seen the implementation plan; a check-author needs `Write`, and this operator's standing policy
grants only read-only `Explore` dispatch (`docs/design.md`, Resolved decisions, 2026-07-28). Same
named deviation as moves 4b/5/7 — recorded, not silently taken. The mitigation actually available
here is that the criteria were authored at triage and in D2 *before* the implementation approach
existed, and the freeze commit predates every line of implementation.

---

## C1

CRITERION: GIVEN an issue list in which issue N carries the park label and issue M does not, WHEN
selection computes the park list, THEN N SHALL appear in it and M SHALL NOT.

CHECK: `bash driver/test-park-state.sh` — section `C1`. Extracts the real function with
`eval "$(sed -n '/^parked_numbers()/,/^}/p' driver/agent-session-driver.sh)"`, feeds it a fixture
`gh issue list --json number,labels` payload carrying both cases, asserts it prints exactly `7`.

AT FREEZE: **fails** — `expected: 7 / actual: (empty)`. The correct reason: `parked_numbers` reads
`$PARKED_LOG` and never looks at a label, so it returns nothing for an issue list it does not
consult. Not an extraction error — `declare -f parked_numbers` succeeds, so the sed extraction found
the real function.

## C2

CRITERION: WHEN a run's outcome is one of `parked|failed|incomplete|no-gate`, THE DRIVER SHALL add
the park label to that issue, on the normal path AND on the `--classify-only` recovery path.

CHECK: `bash driver/test-park-state.sh` — section `C2`. Invokes the shipped driver as a subprocess
once per path, with `gh` and `claude` stubbed on `PATH`, against a PR whose gate block reads
`verdict: pending` (→ `incomplete`). Asserts the stub's argv log records `--add-label`, the label
name `driver-parked`, and `issue edit 7`, once per path.

AT FREEZE: **fails, 6 assertions, both paths.** The argv log contains exactly three calls —
`pr list`, `pr view --json body`, `pr view --json headRefOid` — and no label write of any kind. The
driver's outcome is `incomplete` on both paths, so the parking branch *is* being taken; what is
absent is the label write, which is the criterion.

## C3

CRITERION: WHEN a run's outcome is `gate-eligible` or `gate-human`, THE DRIVER SHALL remove the park
label from that issue.

CHECK: `bash driver/test-park-state.sh` — section `C3`. Same harness with
`verdict: eligible-for-auto-merge` and then `verdict: human-merge-required`; asserts a
`--remove-label` call naming `driver-parked`, and no `--add-label` call.

AT FREEZE: **fails, 4 assertions** (`--remove-label` and the label name, for each verdict). The two
`outcome is what the gate said` assertions pass, which is the point: the classifier already reaches
`gate-eligible`/`gate-human` correctly, so the gap is only the un-park write.

**The two `and never adds it` assertions pass vacuously at freeze** — nothing is logged at all, so a
negative assertion cannot fail yet. They are guard-shaped and earn their keep only after the write
side exists. Stated rather than counted as evidence.

## C4

CRITERION: GIVEN issue N carrying the park label, WHEN selection runs with `--state-dir` pointing at
an empty directory, THEN N SHALL be reported as skipped with the park reason, AND `--retry N` SHALL
report it eligible in the same configuration.

CHECK: `bash driver/test-park-state.sh` — section `C4`. Invokes the shipped driver `--dry-run` as a
subprocess against a `gh` stub serving one labeled and one unlabeled marker-carrying `auto-ok`
issue, **with an empty PR list**, and an empty `--state-dir`. Asserts `SKIP    #7  parked`; then
that `--retry 7` yields `ELIGIBLE #7`; then, against a `--state-dir` seeded with two ledger rows for
#7, that the skip line cites the newer `reason` and not the older one.

AT FREEZE: **fails, 2 assertions** — `SKIP    #7  parked` (actual: `ELIGIBLE #7  tier: auto-ok`, the
label ignored) and `current reason` (same cause: no skip line, so no reason line).

**Two assertions here pass vacuously at freeze** and are recorded as such: `--retry makes the parked
issue eligible again` (everything is eligible today) and `and not the first appended one` (there is
no reason line to cite the wrong row). Their discriminating twins are the two that fail.

## Guards

(Pass today; must keep passing. Not criteria — they can't fail at freeze.)

- **G1:** `make check` — `driver-check` + `gate-test` + `driver-test` + `skill-readonly`. Passed at
  freeze: **61 bash assertions, 0 failed**, plus the pytest suite, plus both greps. No test may be
  lost, newly skipped, or newly failing.
- **G2:** `make driver-check` — no executable merge path in the driver. Passed at freeze.
- **G3:** `budget-exhausted` stays out of the parking case list at both sites. Passed at freeze,
  asserted inside `driver/test-driver.sh` (the `budget-exhausted is excluded from the park list`
  assertion), which G1 runs.
- **G4:** `make skill-readonly` — the `$SKILL_DIR` deny rules survive. Passed at freeze.
- **G7:** `git diff origin/main..HEAD --stat -- skills/ driver/gate.py` is **empty**. Both are
  risk-gated in `CLAUDE.md`. Passed at freeze (empty).

G5 (`--retry` bypass) and G6 (the skip reason cites the current record) were **retired as guards and
absorbed into C4** in D2: their seeding mechanism is the store being replaced, so as guards their
commands would have had to be rewritten mid-run.

## Harness sanity

Not criteria and not guards — the section that makes the failures above attributable. A stub bug and
an absent behaviour look identical from outside the harness, so seven assertions prove the fixtures
work before any criterion is judged: the `gh` stub serves the issue list and the PR gate, the ledger
row gets written, and the `claude` stub carries a real-shaped result through the normal path.
**All 7 passed at freeze.**

They earned their place immediately. Three fixture defects were found here, *before* the freeze
commit, each of which would have produced a green-looking or wrongly-attributed check:

1. C1 died on `PARKED_LOG: unbound variable` under `set -u` — a bash error, not an empty park list.
2. C4's skip assertion **passed for the wrong reason**: the shared fixture served an open PR for #7,
   so `SKIP #7 already has an open PR` satisfied a row about the *label*. Adjacent evidence, this
   project's most-repeated defect class, inside the check meant to catch it.
3. `and says why` matched the fixture's issue **title** (`parked issue`) rather than a skip reason.
   Same class again. The titles no longer contain the word and the needle is now
   `SKIP    #7  parked`.

## Amendments

(Append-only. Empty unless an amendment was made.)

### 2026-07-29 — CLARIFICATION to C2 and C3 (no tier change)

**Found by the independent verifier**, not by the implementer. Its report: in C2 the flag, the label
name and the issue number were three *independent* substring matches over the whole concatenated
argv log, and `$PARK_LABEL` also appears in the logged `gh label create` line — so
`with the park label` was satisfiable by the create call, independent of the edit call.

**Old wording** (three assertions per path):
```
has "recovery path: labels the issue"     "--add-label"  "$CO_ARGV"
has "  with the park label"               "$PARK_LABEL"  "$CO_ARGV"
has "  on the right issue"                "issue edit 7" "$CO_ARGV"
```
**New wording** (one assertion; a single call line must carry both needles, order-tolerant):
```
has_call "recovery path: labels the right issue with the park label, in one call" \
         "$CO_LOG" "issue edit $ISSUE" "--add-label $PARK_LABEL"
```
Same shape for the normal path and for C3's `--remove-label`.

**Classified a clarification, not an amendment, by running the mechanical test rather than
asserting it.** Both wordings, both trees:

| | verdict at freeze (`29968c9`) | verdict vs. implementation |
|---|---|---|
| old wording | FAIL — C2 ×6, C3 ×4 | PASS |
| new wording | FAIL — C2 ×2, C3 ×2 | PASS |

No verdict changes at either tree, so no criterion or guard changed what it asserts, and **no tier
downgrade is owed.** Only the assertion count moves, 27 → 21, as three loose matches collapse into
one precise one. The `AT FREEZE` counts recorded above describe the original wording and are left as
written — this section is the explanation for the difference.

**The clarification is load-bearing, not cosmetic**, which was tested directly. Mutating the driver
to `--add-label some-other-label` while still creating the right label — the exact cheat the loose
wording allowed:

```
cheat applied, tightened wording -> 19 passed, 2 failed
cheat applied, original wording  -> 27 passed, 0 failed
```

**Consequence for the tamper check:** `git diff 29968c9 -- driver/test-park-state.sh` is no longer
empty, and that is expected. The diff is this clarification and nothing else.

**Adjudicated by Les**, 2026-07-29, presented with the table above before the edit was made.

#### Corrections to this entry, from the post-clarification verifier run

The second independent verifier audited this entry against the actual diff and found two
descriptive gaps. Neither is an undescribed behaviour change — it re-confirmed that all four hunks
are the C2/C3 tightening and that no assertion, fixture, stub or criterion line moved outside them —
but both are recorded rather than quietly fixed:

1. **The entry quotes the new wording without stating that a new `has_call()` helper and its comment
   block were added.** The addition is implied by the quoted invocation, not enumerated.
2. **"three assertions per path" is right for C2 and wrong for C3**, where the collapse is two → one
   (`removes the park label` + `naming that label`). The stated arithmetic, 27 → 21, is unaffected
   and matches the observed count.

#### Residual looseness, stated rather than closed

The same run probed the tightened predicate directly. `has_call` uses unanchored substring
containment on one line, so it closes the cheat it was written for — the `gh label create` line no
longer satisfies it — while remaining satisfiable by:

- `issue edit 70 ... --add-label driver-parked` — any issue number with `7` as a **prefix**;
- `issue edit 7 ... --add-label driver-parked-oops` — any label with the park label as a prefix;
- a single call that adds *and* removes the label (C2 has no `hasnt "--remove-label"` counterpart;
  C3's `hasnt "--add-label"` does cover the mirror case).

**Left as-is deliberately, and this is a judgment worth seeing.** The driver's actual calls are
`--add-label "$PARK_LABEL"` and `--remove-label "$PARK_LABEL"` on `issue edit "$1"`, verified today,
so only the intended call matches in practice. Against that: each further edit to a frozen file costs
tamper-diff clarity and needs its own adjudication, and chasing exact-match precision inside a
substring harness has falling returns. The first-listed case is the one with a non-adversarial
failure mode (label the wrong issue, pass anyway) and is the one to close first if this is revisited.

## Tamper verdict, recorded pre-squash

`git diff 29968c9 -- driver/test-park-state.sh` — **non-empty, and expected.** 29 changed lines in
four hunks, all of them the logged C2/C3 clarification above; verified independently, twice. Recorded
here because `git reset --soft origin/main` collapses the freeze commit and the baseline stops being
reachable from the branch, so this record — not the command — is the evidence the gate cites.

Blob hashes: `d8b0855` at the freeze commit `29968c9`, `361b884` in the pushed tree.
