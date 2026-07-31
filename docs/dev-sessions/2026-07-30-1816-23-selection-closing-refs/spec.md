# Spec — issue #23

**Source:** https://github.com/lmorchard/agent-sessions/issues/23

_Captured verbatim from the issue body (marker line stripped)._

---

`pr_for_issue()` (`driver/agent-session-driver.sh:324-332`) decides whether an issue "already has an
open PR". It matches a **bare `#N`** anywhere in an open PR's body or title, or the bare number
anywhere in the branch name. So a PR that merely *mentions* issue N is indistinguishable from a PR
that *implements* it — and the mentioning PR silently removes N from selection.

## Found live, while verifying an unrelated triage pass

PR **#21** is a docs-only PR. Its body carries a table listing `#11 #12 #13 #18 #19 #20`, and its
branch is `docs/triage-11-12-13`. Running the driver's own jq over the driver's own `gh pr list` query:

```
issue 11 regex match: 21  https://github.com/lmorchard/agent-sessions/pull/21
issue 13 regex match: 21  https://github.com/lmorchard/agent-sessions/pull/21
closingIssuesReferences per open PR:
21	docs/triage-11-12-13	[]
```

**GitHub itself links PR #21 to no issue.** The driver links it to #11 and #13, both `auto-ok`, and
both dropped from `ELIGIBLE` to `SKIP  already has an open PR` at `agent-session-driver.sh:391`.
`eligible` went 3 → 1.

Reproduced two independent ways: against live GitHub, and by extracting the shipped function
(`eval "$(sed -n '/^pr_for_issue()/,/^}/p' ...)"`, the `test-park-state.sh:180` pattern) and calling it
on a verbatim PR-21 fixture — `pr_for_issue 11` returns PR 21, `pr_for_issue 99` returns empty.

## Class, and why this direction is worse than #19

`docs/findings.md` class 1 — **a row satisfied by evidence adjacent to what it names.** The code's own
comment at `:318` says *"An express PR carries `Closes #N`"* and then the implementation never requires
the keyword, so a mention *adjacent to* a closing reference satisfies a check that names the closing
reference.

Compared with #19, which has the same loose-match shape: #19 wrongly **admitted** a candidate that a
later stage dropped — a wasted stage, self-correcting. This wrongly **excludes** eligible work, and
nothing downstream ever catches it. The driver idles and prints a skip reason that reads as true. It is
a **liveness** bug, not an output-correctness bug.

It is also **self-amplifying in exactly this repo's workflow**: one triage or docs PR listing six issue
numbers blocks six issues at once, so the more the project documents its own triage, the more of its own
backlog it hides.

## The authoritative signal is free

`closingIssuesReferences` is available on the **list** query `fetch_open_prs` already makes
(`agent-session-driver.sh:319`) — verified: `gh pr list --json number,title,body,headRefName,url,closingIssuesReferences`
exits 0 with the field populated. No second API call, no `gh pr view`. There is no API-cost argument
against fixing this properly.

## Verifiable acceptance criteria

- CRITERION: GIVEN an open PR whose body mentions `#N` in prose with no closing keyword, whose branch
  name contains N, and whose `closingIssuesReferences` is empty, WHEN the select stage runs on an
  `auto-ok` issue N, THEN the driver SHALL report `ELIGIBLE #N` and SHALL NOT report
  `SKIP    #N  already has an open PR`.
  CHECK: a new node in `driver/test-driver.sh` following the **field-honouring** `gh`-stub +
  `--dry-run` pattern at `:456-487` — stub `pr list` with PR 21 verbatim (body table containing `#11`,
  `headRefName: docs/triage-11-12-13`, `closingIssuesReferences: []`), an issue fixture with #11
  `auto-ok`, then assert the output contains `ELIGIBLE #11` and does not contain the skip line. Graded
  by running the shipped driver as a subprocess, so deleting the behaviour flips it — **not** a
  `grep -q "<literal>" "$DRIVER"` spelling check.
  VERIFIED DISCRIMINATING: yes. Ran the unit-level equivalent against the real shipped function —
  `pr_for_issue 11 '<PR 21 fixture>'` returns `21 https://github.com/.../pull/21` where empty is
  expected. The same call returns empty for issue 99, so the fixture can both fail and pass; it is not
  vacuous in either direction.
  Oracle exists now: yes — the stub harness, the `--dry-run` path and the `SKIP`/`ELIGIBLE` output
  vocabulary all exist. Only the assertion is new, and the fixture is a transcript of live GitHub
  output rather than a judgment call.
  Satisfiable without the work: no cheap fake. Cheapest green is a real change to the match. Deleting
  the PR-skip arm entirely would also green it — G2 is what stops that.

- CRITERION: WHEN `fetch_open_prs` queries GitHub, the driver SHALL request `closingIssuesReferences`,
  so the authoritative issue link is available to the matcher without a second API call.
  CHECK: the same test node, using the `:456-487` stub that **honours** the requested `--json` field
  list — serve a PR whose body and branch carry no number at all but whose `closingIssuesReferences` is
  `[{"number":11}]`, and assert `SKIP    #11  already has an open PR`. Only a driver that actually asks
  for the field can see it, because the stub filters on the requested list.
  VERIFIED DISCRIMINATING: yes — no PR in today's fixture set carries the field, so the assertion
  cannot pass against today's driver. The field's availability was confirmed live (exit 0, populated).
  Oracle exists now: yes.
  Satisfiable without the work: no — a driver that omits the field from its `--json` list sees `null`.
  **This is the slice `test-driver.sh:444-455`'s own comment was written for**, and it is the mutation
  `docs/findings.md` records as having gone undetected once already: a stub that ignores the requested
  field list cannot see a missing field.

## Regression guards

- GUARD: the extracted `pr_for_issue 7` still returns its PR for the **frozen** fixture at
  `driver/test-park-state.sh:89` — body `Closes #7`, branch `fix/7-stub`, and **no
  `closingIssuesReferences` field at all** (its stub ignores the requested field list).
  RAN: returns `42  https://github.com/stub/repo/pull/42`. Passes today.
  **Why this is the load-bearing guard:** `pr_for_issue` has two callers with opposite needs — the
  selection gate at `:384` wants *precision*, while post-run PR discovery at `:622` and `:746` wants
  *recall* and runs against a PR the driver may have opened badly. A closing-refs-only fix applied to
  the discovery sites makes that frozen fixture resolve to nothing, flipping its cases to
  `parked: no PR opened`. `test-park-state.sh` is frozen and read-only, so that is a **STOP**, not an
  edit.
- GUARD: the extracted `pr_for_issue 8` returns empty for the same frozen fixture — the gate still
  gates. Protects against "fixing" this by deleting the match, since an over-broad matcher and a
  deleted matcher both green the first criterion.
  RAN: returns empty. Passes today.
- GUARD: `bash -n driver/agent-session-driver.sh` exits 0. RAN: exit 0. Passes today.
- GUARD: no existing `driver-test` or `park-test` assertion is lost, newly skipped, or newly failing.
  Stated as an invariant, not a count. **UNRUN** — the triage scan operated under a no-full-suites cap.
  Must be run once before merge.

## Tier: `auto-ok`

**Re-derived 2026-07-29 after Les answered open question 1 with "yes".** Bare branch-number matching
may be dropped at the selection gate in favour of `closingIssuesReferences`. That resolves the fork,
so **trigger 1 no longer fires** — both criteria hold unchanged under the chosen design, their oracles
exist, and neither is satisfiable without the work.

**Trigger 2 does not fire.** The fix touches `driver/agent-session-driver.sh` and
`driver/test-driver.sh`, both drivable per `CLAUDE.md` ("the rest of `driver/` ... is drivable"). It
does not touch `driver/gate.py` — selection runs upstream of classification — and it does not touch
`skills/**`. No auth, secrets, data migration/deletion, deploy/infra/CI config or dependency change.

**The two remaining open questions do not affect the tier**, because neither changes which criteria
apply: one function with a strictness flag versus two functions is implementation style, and whether
to print an advisory line is additive. Both carry defaults below.

**One constraint the implementer must not lose, and it is what makes this `auto-ok` rather than
trivial:** the answer applies to the **selection gate only**. `driver/test-park-state.sh:89` is frozen
and read-only and pins the *loose* behaviour at the two post-run discovery call sites. Guard G1 exists
to catch a fix that over-applies the decision; tripping it is a **STOP**, not an edit.

### Original tier assessment (superseded)

Recorded because the option analysis is still the evidence, and because a reader should be able to see
what the decision resolved. Before the answer, this was `needs-review` on trigger 1's
withheld-decision route: the first criterion **fails** under one of three candidate designs, so the
loop would have been picking the goal rather than implementing it.

| Option | Does it fix the live bug? |
|---|---|
| (a) `closingIssuesReferences` only | yes — but breaks the frozen fixture at the discovery call sites unless a fallback is kept |
| (b) keep the regex, require `Closes\|Fixes\|Resolves` | yes |
| (c) `closingIssuesReferences` **OR** branch-name | **no** — PR #21's branch was `docs/triage-11-12-13`, so #11 and #13 still skipped |

Option (c) is refuted by data rather than taste, and it is the compromise a reader reaches for first.
The trade-off Les weighed in choosing (a): a human who opens a PR from `fix/11-foo` without writing
`Closes #11` would newly get their work duplicated — accepted, because both merged express PRs (#10,
#14) carried `Closes #N` *and* a numbered branch, and `references/pr-body-template.md:52` plus
`phases/pr.md:78` mandate the keyword in every PR the skill writes.

## Design decisions

- **Decision (Les, 2026-07-29):** at the **selection gate**, an issue counts as having an open PR only
  via `closingIssuesReferences`; bare branch-number matching is dropped there.
  - **Why:** it is the only option that actually fixes the observed bug — the branch arm fired
    independently on PR #21, so the `closing-refs OR branch-name` compromise still hid #11 and #13. The
    authoritative signal is free on the list query the driver already makes, and every merged express
    PR has carried `Closes #N`, which the PR template mandates.
  - **Rejected:** option (c), refuted by data above; and keeping the loose matcher everywhere, which is
    what caused this.
  - **Accepted cost:** a human who opens a PR from `fix/11-foo` without writing `Closes #11` will get
    their work duplicated by an unattended run.
  - **Scope limit:** selection only. The two post-run discovery call sites keep the loose matcher, which
    the frozen fixture at `driver/test-park-state.sh:89` requires.

- **Decision:** the criterion is graded by running the shipped driver as a subprocess against a
  field-honouring stub, not by grepping the driver's source.
  - **Why:** `docs/findings.md` class 5 catalogs eight live `grep -q "<literal>" "$DRIVER"` assertions
    in `test-driver.sh` as spelling checks rather than tests. The second criterion additionally
    *requires* a field-honouring stub, because a stub serving a fixed payload cannot see a missing
    `--json` field — a mutation this project has already watched pass unnoticed.
  - **Rejected:** a source grep for the new match expression.

- **Decision:** treat this as a **selection-vs-discovery split**, not a one-line `jq` swap.
  - **Why:** the two call sites want opposite error directions, and the frozen fixture pins the loose
    behaviour for the discovery pair. A single matcher cannot serve both without one of them being
    wrong.
  - **Rejected:** tightening the shared matcher, which is a STOP against a read-only frozen check.

## What we're NOT doing

- **Option (c).** Refuted above by PR #21's own branch name; recorded so nobody re-proposes it.
- **Editing `driver/test-park-state.sh`.** It is frozen and read-only. If a fix appears to require it,
  stop and surface rather than editing.
- **Changing `driver/gate.py`.** Selection runs upstream of classification; the classifier is untouched.
- **Retro-fixing PR #21's body or branch name.** The bug is the matcher, not the PR. (Merging or
  closing #21 does clear the live symptom, since the query is `--state open`.)

## Open questions

1. ~~May bare branch-number matching be dropped at the selection gate in favour of
   `closingIssuesReferences`?~~ **RESOLVED yes, 2026-07-29** — see Design decisions. This was the
   trigger-1 question; answering it is what moved the tier to `auto-ok`.
2. **One function with a strictness flag, or split into a strict `pr_blocking_issue` (`:384`) and a
   loose `pr_from_run` (`:622`, `:746`)?** **Default: split** — the two callers want opposite error
   directions, and the frozen-fixture guard exists only because they currently share one matcher.
3. **Should a mention-only match still be *reported* rather than silently ignored** — e.g.
   `ELIGIBLE #11  (PR #21 mentions it, no closing link)`? **Default: yes, one advisory line.** A null
   rendering as a positive is `findings.md` class 2, and silently discarding the near-match is the same
   shape in reverse.
