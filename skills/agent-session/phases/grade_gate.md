# grade_gate

Evaluate the merge gate and set the verdict.
This phase is triggered by the orchestrator when a PR has passed CI and has no unresolved review comments.

## Inputs
- GitHub PR URL
- The GitHub issue this resolves
- `checks.md` (if available, for large/architectural tasks)
- `spec.md` (if available)

## Outputs
- **A gate verdict reported**: `eligible-for-auto-merge` or `human-merge-required` + reason in the PR block.

## Process

1. **Derive the verdict.** Not a judgment call — read each row and take the result. *(For small tasks without frozen checks, ignore the first four rows and grade solely on local project gates, CI checks, unresolved threads, tier, and risk-gated paths).*

    | Condition | Source |
    |---|---|
    | Every criterion with a check: `pass` | The independent verifier's report (step 12's, if it re-ran) |
    | Every human-judgment criterion: graded by a human | `checks.md` evidence + an actual human answer |
    | Every guard still `pass` | The verifier's report — a pass→fail flip is a regression you caused |
    | Tamper diff clean, or every difference logged as an amendment | The verdict recorded at step 5 — and still re-runnable, since the freeze commit is an ancestor of the pushed head. `clean-by-substitute` counts, bare `clean` on an empty `Check files` list does not |
    | Local project gates green | `make check` in the worktree |
    | CI checks on the pushed head all pass | `gh pr checks` — the query below. A local `make check` is **not** a substitute |
    | No unresolved review threads and no unaddressed human comments | The GraphQL query below AND `gh pr view <n> --json reviews,comments` |
    | Tier is `auto-ok` (and not downgraded by an amendment) | `spec.md` Tier section |
    | PR touches no risk-gated path | The diff vs. `acceptance-criteria.md`'s risk list |

    Unresolved threads, verified working (`gh` has no `reviewThreads` JSON field — asking for one
    errors out and prints the valid list, which is easy to misread as "no threads"):

    ```bash
    gh api graphql -f query='query($owner:String!,$repo:String!,$pr:Int!){repository(owner:$owner,
      name:$repo){pullRequest(number:$pr){reviewThreads(first:100){nodes{isResolved}}}}}' \
      -F owner=<owner> -F repo=<repo> -F pr=<n> \
      --jq '[.data.repository.pullRequest.reviewThreads.nodes[]|select(.isResolved==false)]|length'
    ```

    Note that a bot review carrying **no** inline comments produces zero threads while still
    registering as a review — so check the review itself landed (`gh pr view <n> --json reviews,comments`)
    rather than reading `0 unresolved` as proof a reviewer ran. 
    Also verify there are no new human PR comments or top-level reviews (like "COMMENTED" or "CHANGES_REQUESTED") that need addressing. If there are new human comments since you last updated the PR, you must count them as unresolved review threads. If no review has arrived yet,
    report `threads: no review yet` and set `verdict: pending` — a review that hasn't arrived is not
    a failure and not a pass; it is not yet derivable.

    **Rules on resolving review threads (audited autonomy):**
    - **For `auto-ok` tier issues:** You may address feedback, reply to comments, push fixes, and resolve your own threads. As long as CI and all project-gates are completely green, the gate trusts the self-resolution.
    - **For `needs-review` tier issues:** Do NOT resolve review threads yourself (unless a separate "Auditor" subagent is explicitly configured to audit and resolve). Instead, leave them unresolved for the human reviewer to verify and resolve (Human-in-the-loop review). If you resolved any yourself on a `needs-review` issue, they count as unresolved for gate purposes.

    **The CI row is a claim about a commit, so derive it LAST — after the final push — and record
    the sha it describes.** Anything that pushes afterwards invalidates it: a force-push to amend
    session docs starts a new check run, and the row you already wrote now describes a commit that
    is no longer the head. Measured: a run verified `2/2 pass`, then amended docs and force-pushed,
    and published `ci: 2/2 pass · verdict: eligible-for-auto-merge` on a head whose `lint-and-test`
    was `pending` and whose `mergeStateStatus` was `UNSTABLE`.

    So: **the last push happens before the CI wait, not after.** If you must push again, the row is
    void — re-wait and re-derive, or set `verdict: pending`. Confirm the sha you graded is still the
    head before writing the verdict:

    ```bash
    gh pr view <n> --json headRefOid -q .headRefOid      # before and after; must match
    ```

    This is the same defect as *"the tree you ran the checks on is not the tree you pushed"* from the
    #649 run, one level up — there it was a working tree, here it is a commit. Both are the gate
    citing evidence gathered against something other than what ships.

    **Read `bucket`, never `state`** — `state` is GitHub's raw value (`SUCCESS`), while `bucket` is
    the normalised `pass | fail | pending | skipping | cancel`. A filter written against
    `.state != "pass"` counts *passing* checks as failures and makes every green PR ineligible:

    ```bash
    gh pr checks <n> --json name,bucket \
      --jq '{total: length, bad: [.[]|select(.bucket!="pass" and .bucket!="skipping")]}'
    ```

    Three things this row must not do:

    - **Don't use `--required`.** On a repo with no required checks it prints `no required checks
      reported` and exits 1 — so the row either errors or passes vacuously depending on how you read
      it. Grade *all* checks.
    - **Report `total`.** A repo with no CI at all yields an empty list, and "nothing failed" is not
      "everything passed". Zero checks is a fact for the gate block to state, not a green light.
    - **Don't substitute the local `make check`.** It is a different machine, a different
      environment, and it is the row above. This row exists because a run once reached
      `eligible-for-auto-merge` with `lint-and-test` still `pending`.

    **Pending CI is transient, and that makes it the one row you wait on** rather than fail. Checks
    take minutes; the other rows are already settled. Wait with **exactly this**:

    ```bash
    gh pr checks <n> --watch
    ```

    One blocking command that returns when the checks finish. **Do not build a wait out of anything
    else** — a `sleep` poll loop, a backgrounded shell, and the `Monitor` tool are all *denied* under
    the `--permission-mode dontAsk` floor an unattended run uses. Measured: a run burned its entire
    budget trying all three, never tried `--watch`, and ended at `verdict: pending` on a PR whose CI
    went green minutes later. `--watch` is a single `gh` invocation, so it is covered by the same
    allow-rule as every other `gh` call, and it costs one turn instead of one turn per poll.

    If the checks genuinely never settle, the verdict is **`pending`** — not
    `eligible-for-auto-merge` and not `human-merge-required`: nothing is wrong, it just isn't
    derivable yet, and `pending` is the value a machine reader already knows not to act on.

    **All true → `eligible-for-auto-merge`. Any false → `human-merge-required`**, with the
    failing row as the reason. Write the verdict into the gate block and report it.
    If the verdict is `eligible-for-auto-merge`, update and append any newly discovered architectural rules, stylistic choices, or test patterns to `docs/agent-ledger.md`.

    Any row satisfied by a substitute rather than by its cited mechanism is still a pass, but
    **name the substitute in the gate block** where the row would otherwise read as a clean
    mechanical result. A row that silently reports the mechanism's absence as the mechanism's
    verdict is the one failure this table cannot survive.

    A `needs-review` tier is never eligible, however green the checks. That's the tier doing its
    job — it was set because something here isn't check-decidable.

2. **Stop.** Report the PR URL, the verdict + reason, what was fixed, and what was skipped or
    deferred. Do not merge — no `gh pr merge`, with or without `--auto`. `eligible-for-auto-merge` is a
    *finding*; the unattended loop that acts on it lives above this skill.

## When to skip

Work that won't end in a PR (direct-to-main, throwaway, keep-local) — see
`superpowers:finishing-a-development-branch` for the merge/PR/keep/discard pattern with the
right worktree cleanup for each.

Unfinished work and red checks are preconditions, not skip conditions: fix them, then run `pr`.

