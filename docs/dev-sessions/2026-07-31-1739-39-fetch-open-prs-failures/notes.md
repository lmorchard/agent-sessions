# Session notes — issue #39, `fetch_open_prs` swallows gh failures

Unattended `express` run, 2026-07-31. Tier `auto-ok`, no human watching.

## What shipped

`fetch_open_prs` stopped deciding things. It drops `2>/dev/null || echo '[]'` and now propagates
`gh`'s stderr and exit status; the callers split on it:

- **`select_issues` refuses** (`die`, exit 2, before the run loop). Every "already has an open PR"
  skip and every ELIGIBLE that depends on no such PR existing derives from that one value.
- **Both discovery sites degrade distinguishably** — the run path in `run_issue` and the
  `--classify-only` recovery path. The outcome stays `parked`; only the reason changes, so the
  ledger row for a run that already cost money survives while it stops asserting `no PR opened`
  about a PR the driver never managed to look for.

Both discovery sites were `pr_for_issue "$n" "$(fetch_open_prs)"`. Command substitution discards
the inner exit status — that nesting is *why* the failure was invisible there — so they are now
two statements each.

## Things worth carrying forward

**The `set -euo pipefail` trap shaped the code.** `cond && var="$(...)"` aborts the script when
`cond` is false, because the compound returns non-zero. Every conditional assignment in this diff
is `if/then/fi` for that reason, not for style. Worth knowing before the next driver edit.

**A vacuous check nearly shipped, and the fix was a control case.** C1's load-bearing clause is
"invokes `claude` zero times", and the `claude` stub logged nothing — so the count would have read
zero whether or not the behaviour existed. The check-author added argv logging *and* a control case
that runs the identical fixture with a healthy query and asserts `>= 1`. The vacuity condition is
now exactly the control's failure condition. This is a reusable shape: **when a check asserts an
absence, pair it with a control that asserts the corresponding presence**, or the sensor's own
death reads as success.

**The independent verifier earned its keep on a count, not on the code.** It found that
`checks.md` said "22 pre-existing park assertions" when the baseline was 21 — the new control had
been miscounted as pre-existing. Logged as a clarification (no CHECK command changed, no verdict
moves at either tree, no tier change). Two notes on this:

- It is this project's defect class 4 again — *a count stated away from its evidence*. The
  guards themselves were written as invariants ("no case lost, newly skipped, or newly failing")
  precisely to avoid this, and the rot landed in the prose beside them anyway.
- It came in via a subagent's summary that I propagated without recounting. The baseline number
  was in my own scrollback the whole time.

**`make check` was green throughout the miscount.** Nothing mechanical catches a wrong number in
a session doc. `docs-check` matches assertion-count claims in tracked docs — it reported
`no assertion-count claims found to check; suite reports 112`, i.e. it is looking at the
driver-test count, not park-test, and not at session-dir prose.

## Branch self-review findings (2026-07-31, post-rebase)

Two findings, both surfaced rather than silently resolved. No code changed as a result.

**1. The `--classify-only` discovery site is fixed but no frozen check covers it.** C2's criterion
says *"during post-run PR discovery"*, and there are **two** such sites — `run_issue` (`:924`) and
`--classify-only` (`:1080`). The frozen check exercises only the first. I fixed both, because
fixing one and not its twin is findings.md class 1, and because the driver's own comment says
`--classify-only` is the call site that matters most, being the documented recovery path.

**I did not add a check for the second site, deliberately.** The check files are read-only from
Phase 1, and more to the point a test I write now, for code I just wrote, has none of the
independence that makes the frozen ones worth anything — it would be the implementer authoring its
own oracle, which is the single failure this system exists to prevent. So the gap is named here and
in the PR body instead of being papered over with a self-authored assertion.

This is not an amendment: the check is not *wrong*, it is *narrower than its criterion*. The
amendment path is for a check that fails to test its criterion; this one tests it, just not
exhaustively. Worth a follow-up issue so the second site gets a check authored by a context that
did not write it.

**2. CLAUDE.md's residual-risk clause has fired, and I cannot be the one to act on it.** That
paragraph leaves the driver's outcome routing drivable and ends *"Revisit if a run ever touches
that routing."* This run touches it — C2 changes park reasons. The spec anticipated this and kept
the tier `auto-ok` on three stated grounds, so this is not a surprise. But **CLAUDE.md is not on
the drivable allowlist**, so an unattended run must not edit it to record that the clause fired.
Flagged for the human at the merge gate; the decision about whether the clause should now gate this
routing is theirs, not this run's.

## Noticed, deliberately not fixed

Out of scope per the spec's *What we're NOT doing*; recorded here rather than fixed, per CLAUDE.md.

- **`gh issue list` at `select_issues` swallows identically** — `2>/dev/null || echo '[]'`. On
  failure the driver reports `read 0 open issues` and selects nothing, which is a null rendering as
  a positive in the same shape, one call over. It is arguably worse than the PR query, because
  "no issues" is a plausible steady state. The spec names widening this as a separate issue.
- **`load_board` swallows too** (`|| echo '{"items":[]}'`), but the board is explicitly advisory
  and says so at runtime (`advisory only; does not gate`), so a silent empty board misleads less.
- Neither was touched. A follow-up issue for the `gh issue list` case is worth filing.

## Process notes for whoever runs this loop next

- **Bash was heavily restricted in this run** (don't-ask mode). Shell redirection (`>`), `rm`,
  `mktemp -d`, and `bash <script>` were all denied; `make`, `git`, `gh`, `grep` and `python3 -c`
  were allowed. Consequences: the spec's pre-freeze evidence re-run had to be done **statically**
  (reading the current source at the re-derived line numbers) instead of by executing the
  demonstration, with the dynamic confirmation arriving at the freeze via `make park-test`. The
  independent verifier hit the same wall and could not run its mutation empirically — its finding
  on C1's non-vacuity rests on the control passing plus reading the source coupling, and it said so
  rather than overclaiming.
- The session-dir files had to be written with the Write tool rather than `gh issue view > spec.md`.
