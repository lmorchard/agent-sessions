# Session notes — #11, `--repo-path /` containment bypass

**Mode:** `agent-session express`, unattended, no human watching.
**Issue:** https://github.com/lmorchard/agent-sessions/issues/11 — tier `auto-ok`.
**Worktree:** `.worktrees/fix/11-repo-path-root-containment`, branch off `origin/main` @ `86fe791`.
**Freeze:** `6f18f87`, sha recorded in `8a8cbd5`.

## What happened

The issue asked for the ordering the whole system exists to enforce: **freeze a check for the bug
first, then fix it.** That is what this run did, and the check failed at freeze with the predicted
discriminating failure (`expected: warned stopped-early` / `actual: no-warn gh-check`) before one
line of the fix existed.

The fix is two executable lines. `pwd -P` returns `/` for the root directory — the one resolved path
that already ends in a separator — so `"$repo_real"/*` built the glob `//*`, which matches no
ordinary absolute path. Every path read as *outside* `/`, and the guard went silent on the one
`--repo-path` that contains everything.

## Three things worth keeping

**1. The plan self-review caught a real defect, not a nit.** The obvious fix is
`[ "$repo_real" = "/" ] && repo_real=""`. That works, and it makes the warning's *own* second log
line print `repo:  ` with nothing after it — degrading the message this change exists to make fire.
Resolved by normalising into a separate `repo_prefix` used only by the glob, leaving `repo_real`
truthful for the log. **The pattern value and the reported value wanted to be different variables**,
and only writing the plan surfaced that.

**2. The permission floor forced a better freeze than the one that was planned.** The intent was to
re-run the issue's original probe by hand
(`PATH=/usr/bin:/bin ./driver/agent-session-driver.sh --repo-path / ...`). Every route to it was
denied by the `dontAsk` floor — `ln` (unlisted mutation), `mkdir` under `/tmp` (outside the working
dir), `env`, a bare `case`, and any output redirect. All of these are already catalogued in
`findings.md` under *"permission denials are triggered by shell syntax, not command names."*

That is worth recording as a **good** outcome rather than friction. A hand-rolled probe on a pinned
`PATH` is exactly the ambient-hermeticity assumption that #18 existed to remove: at the unfixed
behaviour, `--repo-path /` sails past validation, and on a host carrying a real `gh` that is a live
driver run against a real issue — the hazard `findings.md` records as having *actually happened*
("it selected a real issue and created a worktree before it was killed"). Being unable to build the
probe by hand pushed the check into the harness, whose `PATH` is **constructed** and which asserts
`gh`'s absence as a precondition. The mechanism beat the intention.

**3. The verifier caught its author again — on the guards, not the fix.** Dispatched read-only, it
confirmed C1 passes, discriminates, and cannot be satisfied by a message appearing without the
behaviour. Then it volunteered something this context had not asked and would not have noticed:
**G2's three false-positive cases pass for reasons *adjacent* to the concern they name.** All three
use ordinary paths, so none of them enters the branch the fix added. They would catch a *general*
normalisation of `repo_real` — the hole that actually mattered — but they are blind to a defect
confined to the `= "/"` branch. It also found a residual the fix does not close: `pwd -P` yielding
`//` leaves the pattern `///*` and the bug intact.

That is `findings.md` defect class 1 arriving inside a run whose whole point was to land a check
that discriminates. It is recorded in `checks.md` under *Findings surfaced, not fixed*, not patched
— `driver/test-driver.sh` is read-only from Phase 1, and widening the oracle mid-run is the one move
this contract exists to prevent.

## Deviations from the phase files, stated rather than glossed

- **No check-author subagent.** `frozen-checks.md` wants one that has not read the implementation
  plan. That dispatch needs Write access; this project grants read-only `Explore` dispatch only
  (`design.md`, resolved decisions — the same withheld grant that blocks roadmap item 7). The check
  was authored in this context, *before* Phase 1, from a criterion triage had already specified down
  to its two assertions. The verifier half of the contract — the half where independence matters
  most — ran as specified.
- **No rebase.** `origin/main` did not move during the run, so the freeze sha needed no re-anchoring
  and `6f18f87` stayed an ancestor of the branch. Stated because `pr.md`'s step 2 assumes the
  re-anchor; skipping it here is the absence of a rebase, not a skipped step.

## Two guards the issue recorded as UNRUN are now run

The issue could not run them (its triage scan was under a no-full-suites cap, and the `/a/bc` case
needed a `mkdir`). Both are in the suite now — #18 landed the `/a/bc` case — and both were observed
green at freeze. So G2 is three cases *observed*, not two observed and one asserted.

## Follow-ups filed / deferred

See `checks.md` § *Findings surfaced, not fixed* for all four, with reasons. The two substantive
ones are the adjacent-evidence gap in G2 and the `//` residual; the other two are stale line-number
references (one pre-existing in `CLAUDE.md`, one frozen into this run's own comment).
