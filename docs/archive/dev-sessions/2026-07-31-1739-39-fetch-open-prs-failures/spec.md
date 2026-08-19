# Spec — driver: `fetch_open_prs` swallows every gh failure as "no open PRs"

**Source:** https://github.com/lmorchard/agent-sessions/issues/39 (captured 2026-07-31, marker line stripped)

---

Raised by the Copilot reviewer on #38 ([comment](https://github.com/lmorchard/agent-sessions/pull/38#discussion_r3687464758)) and deferred there as pre-existing and outside that spec's scope. Filed so it is not silently skipped.

`fetch_open_prs` (`driver/agent-session-driver.sh:332-336`) ends:

```bash
gh pr list --repo "$REPO" --state open --limit 200 \
   --json number,title,body,headRefName,url,closingIssuesReferences 2>/dev/null || echo '[]'
```

Any failure — auth, network, rate limit, or an unknown `--json` field — becomes an empty PR list, with stderr discarded. "No open PRs" is then indistinguishable from "could not ask", and both are silent.

## Why it matters, per call site

- **Selection (`:465`)** — nothing blocks, so an issue that already has a PR gets picked up again. Duplicate work.
- **Discovery (`:715`, `:839`)** — `pr_for_issue` finds nothing and the run records `parked: no PR opened` about a PR that exists. That is a wrong ledger row, not merely a wasted stage.

## What #38 changed, and what it did not

#38 added `closingIssuesReferences` to the field list. `gh` errors on an unknown `--json` field (verified 2026-07-30: `Unknown JSON field: "bogusFieldName"`, exit 1), so a `gh` too old to know the field now fails this query **deterministically** rather than only transiently. The swallow itself is pre-existing; #38 widened the set of environments that reach it.

## One correction to the reviewer's suggested remedy

The suggestion was to fall back to the previous field list when the primary query fails. That does **not** change blocking behaviour: the strict `pr_blocking_issue` reads `closingIssuesReferences`, so a response served without the field matches nothing — exactly as an empty list does. The fallback's real value is the two *discovery* call sites and the advisory near-match, which do work off the old fields. Worth stating plainly, so a fallback is not implemented in the belief that it repairs selection.

## Suggested shape (not a decision — this needs intake)

1. Stop discarding stderr unconditionally. Distinguish "the query failed" from "there are no open PRs", and say which.
2. Consider whether a failed PR query should make selection **refuse to run** rather than proceed on an empty list. A driver that cannot see open PRs cannot make the selection decision it is about to make, and proceeding is a guess that looks like an answer — `findings.md` class 2 (a null rendering as a positive), one layer down.
3. If a field-list fallback is wanted anyway, it belongs at discovery, and it should say out loud that selection is degraded.

**Triaged 2026-07-31** — the marker now leads this body and the criteria are below.

---

## Verifiable acceptance criteria

*Line references in the author's text above have drifted since filing; re-derived 2026-07-31,
`fetch_open_prs` is at `driver/agent-session-driver.sh:487-490`, the selection gate at `:606`/`:619`,
and the two discovery sites at `:882` and `:1023`. Cited here so the criteria anchor on names rather
than on numbers that will drift again.*

- **C1.** IF the open-PR query fails, THEN the selection stage SHALL report the failure and exit
  non-zero, AND SHALL NOT invoke `claude`.
  **CHECK:** a new case in `driver/test-park-state.sh` whose `gh` stub exits 1 on `pr list` while
  serving the issue list normally — assert the driver's output names the query failure, its exit
  status is non-zero, and the argv log records **zero** `claude` invocations. Run by `make park-test`.
  **The zero-invocations clause is the load-bearing half**: an implementation that prints a warning
  and proceeds satisfies "reports the failure" and still spends $5–20 on duplicate work.
  **DEMONSTRATED FAILING 2026-07-31:** extracting the shipped `fetch_open_prs` by name (the technique
  `driver/test-driver.sh:1184` already uses) and calling it against a `gh` that exits 1 gives
  `stdout: []`, `exit: 0` — byte-identical to a `gh` that succeeds and reports zero open PRs. Feeding
  that result to the shipped `pr_blocking_issue` returns empty, i.e. nothing blocks, i.e. the issue is
  selected and a run is invoked.
  **ORACLE EXISTS NOW:** `make_stubs` (`driver/test-park-state.sh:103`) builds the `gh` stub,
  `run_driver` (`:136`) pins `PATH` and captures an `ARGV_LOG`, and the suite already asserts on
  claude invocation (`:168`). Nothing needs building.

- **C2.** GIVEN the open-PR query fails during post-run PR discovery, WHEN the driver records the
  run's outcome, THEN the recorded reason SHALL name the query failure AND SHALL NOT be the
  `no PR opened` reason.
  **CHECK:** a case whose stub fails `pr list` only at discovery — assert the `runs.jsonl` row's
  `reason` names the query failure and is not the `no PR opened` string. Run by `make park-test`.
  **DEMONSTRATED FAILING:** both discovery sites call `pr_for_issue "$n" "$(fetch_open_prs)"`, so on
  failure they evaluate `pr_for_issue n '[]'`, match nothing, and record `no PR opened` about a PR
  that may exist — a wrong ledger row, not a wasted stage.
  **ORACLE EXISTS NOW:** the suite already asserts on `runs.jsonl` reasons (its C4 block checks that
  the skip reason cites the latest ledger row rather than the first appended one).

- **C3.** WHEN the open-PR query fails, THEN `gh`'s stderr SHALL appear in the driver's output.
  **CHECK:** the same fixture — assert the stub's distinctive stderr text appears in the captured
  driver output. Run by `make park-test`. This asserts *runtime output*, not the presence of a
  literal in the driver's source, so it is a test rather than a spelling check.
  **DEMONSTRATED FAILING:** `fetch_open_prs` ends `2>/dev/null || echo '[]'`; the demonstration above
  produced no stderr at all.

## Regression guards

- **G1.** The two matchers stay split, with their opposite error directions intact: a PR whose
  `closingIssuesReferences` names the issue still blocks selection, and the loose discovery matcher
  still matches a bare `#N`. **CHECK:** `make driver-test` and `make park-test` — no case lost, newly
  skipped, or newly failing. Stated as an invariant rather than a count because re-unifying the two
  matchers is the cheap way to break this and it would show up as a case flipping, not as a number
  moving. Passes today: verified 2026-07-31, `make check` exit 0.
- **G2.** `make assertion-lint` stays green — no new case may assert by grepping the driver for a
  literal. **CHECK:** `make check` exits 0. Passes today. This guard exists because C1 and C3 are
  both about *messages*, which is exactly when a presence-grep looks adequate.
- **G3.** On the success path nothing changes: `fetch_open_prs` still emits the parsed PR list and
  the existing park cases still pass unchanged. **CHECK:** `make park-test`. Passes today.

## Tier: auto-ok

**Trigger 1 does not fire.** All three criteria name specific assertions in an existing bash fixture
harness, and each was demonstrated failing today by running the shipped functions rather than a copy
of them. The one decision the issue withheld — its own suggested-shape item 2 — is now resolved
below, so no criterion is left waiting on a goal choice.

**Trigger 2 does not fire.** The work lands in `driver/agent-session-driver.sh` and
`driver/test-park-state.sh`, both on `CLAUDE.md`'s drivable allowlist. Not `driver/gate.py`, not
`skills/**`. No auth, secrets, data migration, deploy/CI config, or dependency change.

**One exposure named rather than glossed.** C2 edits the driver's **park-reason routing**, and
`CLAUDE.md`'s residual-risk paragraph — which leaves that routing drivable — ends *"Revisit if a run
ever touches that routing."* This is the first issue for which that clause fires. Kept `auto-ok`
deliberately, on three grounds: the change makes a wrong reason *right* rather than flattering a
run's record; the mitigations `CLAUDE.md` relies on all apply (the fixture suite, `make check` in the
PR, and a human at the merge gate); and treating the clause as gating would make the routing
effectively un-drivable, since most driver outcome work touches a reason string. **Whoever reviews
the PR should read the reason-string diff knowing this.**

## Design decisions

- **Decision:** selection **refuses**; discovery **degrades distinguishably**.
  - **Why:** the costs are asymmetric in opposite directions at the two call sites. At selection the
    query failure precedes all spend, and proceeding on an empty list is a guess that looks like an
    answer — `findings.md` class 2, one layer down — so refusing costs a wasted invocation and buys
    out a $5–20 duplicate run. At discovery the money is already spent and a PR may already be open,
    so refusing would destroy the ledger row that is the only record of it.
  - **Rejected:** *refuse everywhere* — one code path, but it throws away the record for a run that
    already cost money. *Warn and proceed everywhere* — cheapest, and leaves the duplicate-work
    window open, which is the defect as filed.
- **Decision:** no `--json` field-list fallback.
  - **Why:** the author's own correction above settles it — the strict matcher reads
    `closingIssuesReferences`, so a response served without that field matches nothing, exactly as an
    empty list does. A fallback does not repair selection, and implementing one in the belief that it
    does would leave the defect in place behind a change that looks like a fix.
  - **Rejected:** falling back to the pre-#23 field list.

## What we're NOT doing

- **Retrying the query.** A retry converts a deterministic failure (a `gh` too old for the field)
  into a slower deterministic failure, and the criteria are about not lying, not about resilience.
- **Touching `driver/gate.py` or the outcome classifier.** Off-limits per `CLAUDE.md`.
- **Re-unifying the two matchers.** G1 pins them apart; see the comment block above
  `pr_blocking_issue` and issue #23.
- **Widening this to every `gh` call in the driver.** Real, and a separate issue — this one is scoped
  to the open-PR query, which is the call whose null a caller reads as a positive.

## Open questions

None. The one open decision at filing time (*should a failed PR query make selection refuse to
run?*) was put to a human on 2026-07-31 and resolved as recorded above, which is what took this issue
from `needs-review` to `auto-ok`.
