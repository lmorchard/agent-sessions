# Session notes — #28, presence-grep assertions

Unattended `agent-session express` run, 2026-07-31. Tier `auto-ok`. Stopped at the merge gate.

## What happened

Five phases, all green: the detector (`scripts/assertion_lint.py`), its wiring into `make check`,
the conversion of the offending assertions in `driver/test-driver.sh`, C3's mutation test, and the
`findings.md` ledger row.

## The one thing worth a human's attention: there were nine, not eight

The issue was built around **eight** presence-grep assertions, verified 2026-07-29 at lines 213,
244, 245, 255, 260, 267, 272, 337. Those eight were confirmed still present at this branch's base.

The detector found a **ninth**, at `test-driver.sh:1127`:

```bash
if grep -q '^verdict: eligible-for-auto-merge$' "$D32_RUNDIR/gate.yaml" 2>/dev/null; then
```

Three facts about it, each verified rather than inferred:

1. **C1's frozen check cannot see it.** C1's command is
   `grep -cE '^[^#]*grep -q[EF]? .*"\$DRIVER"'` — it requires the grep target be `"$DRIVER"`, and
   this one targets `"$D32_RUNDIR/gate.yaml"`. So C1's *check* is narrower than C1's *criterion*
   ("No assertion in `driver/test-driver.sh` SHALL be satisfiable by the searched literal
   appearing in a comment"), which the ninth plainly was.
2. **It landed the same morning this run started.** `git log -L 1127,1127` → `8fc95c7`,
   2026-07-31, part of the #32 work that merged to main as `c46c8e2`. The issue recorded "eight"
   on 2026-07-29. The class recurred in the two days the issue sat in the backlog — which is the
   issue's own thesis, demonstrated live rather than argued.
3. **Narrowing the detector would have hidden it, and nothing in the oracle would have noticed.**
   Restricting the rule to targets matching `"$DRIVER"` still passes all seven frozen tests in
   `scripts/test_assertion_lint.py`. That is *exactly* the residual risk the spec named: *"a run
   that edits `driver/test-driver.sh` and authors the detector in one change could shape the
   detector to pass whatever it left behind, with `make check` still green."*

**Decision: fix all nine; do not narrow the detector.** No amendment was raised and no tier
downgrade taken, because satisfying a criterion more completely than its frozen check demands is
not an oracle edit — the frozen check was left untouched and still passes.

**For the human:** the arguable case against is that the ninth greps a *generated artifact* the
driver just produced, not the driver's source, so "the literal is in a comment" is a weaker hazard
there than for the other eight. A future maintainer might reasonably want the detector to spare
that shape. That is a widening decision, and per `CLAUDE.md` it belongs to a human rather than to a
run that would benefit from it. Left strict.

## Verification posture

- The frozen check for C2 was authored by a **check-author subagent** given the criterion and the
  house pattern but not the implementation approach. It defined the interface; the implementer
  conformed to it.
- **C2's freeze failure was a collection error** (`ModuleNotFoundError`, exit 2), which
  `frozen-checks.md` warns "is not yet a check". Accepted because the missing module *is* the
  criterion's condition, and discharged by requiring the post-implementation run to report a
  **count** (7 passed) rather than a bare pass. It did.
- **Discrimination was demonstrated, not asserted.** Commenting out line 828 of the driver
  (`trap cleanup EXIT INT TERM`) leaves the literal in the file, so the old `grep -q` form would
  still have passed. The converted assertion fails: `expected: 1, actual: 0`. Reverted.
- Guards: G1 **89 passed, 0 failed** (freeze floor 88; the issue's stated 64 was two days stale and
  would have permitted dropping 24 assertions unnoticed). G2 and G3 green.

## Things deliberately not done

- **`CLAUDE.md` was not edited**, though its narrow-oracle section says *"a future check-linter,
  however detector-shaped"* is drivable and that linter now exists. The sentence is not falsified,
  only instantiated — and `CLAUDE.md` is **not on the drivable allowlist**, so under the allowlist's
  own rule it is `needs-review` by omission. Flagged for a human rather than edited.
- **Behavioural conversion of the eight.** Asserting through the shipped code (as
  `test-driver.sh:177-192` does) is strictly better than a count comparison, and it is the
  precedent the issue cites. Each of these would need a driver subprocess with stubbed `gh`/
  `claude`, a state dir and an orphan pid — larger than this issue scopes. C1 asks only that the
  comment-satisfiability be removed. Worth a future session.
- **Linting the `Makefile`.** Out of scope per the issue's first design decision; its `grep -qF`
  guards are legitimate, because `skill-readonly` asserts a deny rule is literally *present*.
- **A carve-out for `grep -q` reading stdin.** Legitimate in principle (grepping captured output is
  behavioural), but neither suite contains one, so the exception would be untested speculation and
  a standing bypass.

## Known gap

`assertion_lint.py`'s `main()` has a "scope matched no files" guard that nothing exercises. Its two
real paths were both observed live — green on the final tree, red during C3's mutation. The guard
is three lines and fails closed. Adding a test for it would mean a second test file, since the
frozen one is read-only; not done.
