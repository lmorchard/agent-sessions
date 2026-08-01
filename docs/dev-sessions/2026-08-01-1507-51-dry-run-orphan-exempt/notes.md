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

## Out of scope, found along the way

- **`make docs-check` is vacuous inside a worktree.** `scripts/docs_check.py:44` puts
  `.worktrees` in `SKIP_DIRS`, and `md_files()` filters on absolute-path parts — so a run
  executed from `.worktrees/<branch>/` scans zero markdown files and prints
  `docs-check: links resolve, tables well-formed, counts match` regardless of content. That is
  every express run, which is the only place doc rot in a session's own artifacts would be
  caught. Not fixed here (unrelated to #51, and it is a detector — `scripts/` is drivable but
  the change belongs to its own issue with its own frozen check). Filed as a follow-up.
