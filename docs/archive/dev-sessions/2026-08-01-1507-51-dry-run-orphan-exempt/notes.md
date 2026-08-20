# Session notes — issue #51, `--dry-run` and the live-orphan refusal

Run mode: `agent-session express`, unattended, invoked by the board-driver.
Tier `auto-ok`, so 2a–2i run straight through with no human stop before the merge gate.

## Environment constraint hit early

This run executes under the driver's `--permission-mode dontAsk` floor, and **invoking `bash`
directly is denied** (so is a `sleep` poll loop, a backgrounded shell, and heredoc-fed commands).
`make`, `git`, `gh`, `python3` and `grep` are allowed.

Consequence for the method: the ad-hoc pre-freeze reproduction the plan phase normally runs
(step 4, "re-confirm the spec's own evidence still holds") could not be run as a throwaway script.
It was folded into the freeze instead — the frozen check *is* that reproduction, and observing it
fail at freeze is the same evidence from a better source, since it runs through `make park-test`
rather than a one-off. This is worth knowing for future runs: `pr.md` already records the same
constraint for the CI wait (`gh pr checks --watch` is the only wait that works).

## The freeze

Freeze commit `fa4ca83`. Manifest at `checks.md`, baseline label inventory at
`g3-baseline-labels.txt` (28 labels, captured from the pristine tree at `050c458`).

Two things worth recording because they were judgement calls, not mechanics:

1. **Two of C1's three assertions fail at freeze, not three.** `and still prints the orphan
   warning` passes today — the driver prints the warning and *then* dies, so only the
   non-refusal is absent. It was left passing rather than contrived into failing; its job is to
   be a guard inside C1, catching the most likely wrong fix (buying exit-0 by short-circuiting
   the warning block). C1 as a criterion is the conjunction, and the conjunction discriminates.

2. **Assertion 3's needle was verified reachable before the freeze was committed.** The control
   proves exit 0 is reachable but discards output, so nothing initially proved `ELIGIBLE #8` is a
   string the driver emits under the *stock* stub fixture (C4 only asserts it after emptying
   `pr-list.json`). Confirmed empirically: PR #42 closes #7 not #8, and #7 is skipped for the
   park-label reason anyway. A frozen check that can never go green is worse than no check.

## STOP: #51's C1 contradicts #27's frozen guard G1

**This is where the run stopped. It is a decision, not a defect in the work.**

The implementation is one edit to the startup orphan block. After it:

- `make park-test` — **35 passed, 0 failed.** C1 green, #51's own G1/G2 green, all 28 baseline
  labels still `ok` (G3 green).
- Tamper diff vs `fa4ca83` — **empty.** No frozen check in this run's manifest was touched.
- `make check` — **RED.** `driver-test` reports `111 passed, 1 failed`:

```
  FAIL  #27 G1 a live in-flight run STILL stops a second run against the same repo
     expected: refuse=yes orphan=yes
     actual:   refuse=no orphan=yes
```

### Why this cannot be fixed inside this run

`driver/test-driver.sh:1602-1605` is a **frozen acceptance guard belonging to issue #27**, and it
asserts, with a live same-repo orphan and the `--dry-run` flag (`:1603`), that the driver prints
`refusing to start a second run`. Issue #51's C1 asserts that in that exact configuration it does
**not**. The two are contradictory by construction: same flag, same fixture shape, opposite
expected outcome. No implementation satisfies both.

The mechanical clarification-vs-amendment test in `references/frozen-checks.md` returns
**amendment**, unambiguously: #27 G1's wording passes at the freeze commit `fa4ca83` and fails
against the current implementation, so the verdict *differs vs. implementation*. Amendment means
STOP, human confirmation, a logged entry, and a tier downgrade to `needs-review`.

And this case is stronger than the one that rule was written for. That rule governs amending a
check in *this run's own* manifest. #27 G1 is not in this run's manifest at all — it belongs to a
different, already-merged issue's frozen suite. `spec.md`'s tier reasoning says the work lands in
`driver/agent-session-driver.sh` and `driver/test-park-state.sh`; it never mentions
`driver/test-driver.sh`, so intake did not authorise touching it and did not know the conflict
existed. Editing it to green my own criterion is the implementer editing an oracle that stands in
its way — the single failure this system exists to prevent.

### The substantive question for the human

There is a real argument that #27 G1 over-specified, and it should be weighed rather than assumed:

- **For amending #27 G1.** Its own comment (`:1588-1595`) states its intent as *"the same-repo
  refusal must survive... two drivers mutating one checkout at once — the thing the guard exists
  to prevent."* #51 preserves that intent exactly: its own G1 asserts a real `run` against the
  same live-orphan fixture still refuses **and still invokes `claude` zero times**, and that
  assertion is green. What #51 removes is the refusal only for an invocation that cannot mutate
  anything. On this reading #27 G1 used `--dry-run` as a convenient probe (#27 was about per-repo
  state-dir resolution, and dry-run was the cheap way to reach selection) and thereby froze
  *"`--dry-run` refuses"* as if it were the property, when the property was *"the refusal
  exists"*.
- **Against.** #27 G1 was written precisely as the anti-deletion guard against making the orphan
  check permissive, and #51 is a request to make it permissive. A prior run decided this
  deliberately. "The check is inconveniently strict" is what a correct check feels like from the
  inside, and I am the wrong party to grade my own case.

**If confirmed, the amendment would be:** in `driver/test-driver.sh`, change #27 G1 to probe the
refusal with a spending invocation (a real `run`) rather than `--dry-run`, preserving its stated
intent while removing the contradiction — and downgrade this run to `needs-review`. I have not
made that edit.

### A third path I considered and rejected, stated so it is on the record

#27 G1 uses the *default* state dir (cwd `.driver-state` / XDG) while #51 C1 passes an explicit
`--state-dir`. An implementation that refused under the default but not under an explicit
`--state-dir` would thread the needle and leave both suites green. **Rejected.** That rule is
incoherent on its own terms — the state dir's spelling has nothing to do with whether an
invocation can spend — and it would exist for no reason other than to keep two contradictory
oracles simultaneously green. That is oracle-gaming with extra steps, and it would ship a
behaviour nobody asked for and nobody could explain.

## Out of scope, found along the way

- **`make docs-check` is vacuous inside a worktree.** `scripts/docs_check.py:44` puts
  `.worktrees` in `SKIP_DIRS`, and `md_files()` filters on absolute-path parts — so a run
  executed from `.worktrees/<branch>/` scans zero markdown files and prints
  `docs-check: links resolve, tables well-formed, counts match` regardless of content. That is
  every express run, which is the only place doc rot in a session's own artifacts would be
  caught. Not fixed here (unrelated to #51, and it is a detector — `scripts/` is drivable but
  the change belongs to its own issue with its own frozen check). Filed as a follow-up.
