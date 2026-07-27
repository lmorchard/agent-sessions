# pr

Self-review, squash, push, open a PR, run the review cycle, and **stop at the merge gate**.

Reads `references/frozen-checks.md` (gate condition), `references/pr-body-template.md` (body +
gate block), `references/github-projects.md` (board hook).

The gate is where this mode ends: it reports whether the gate is satisfied and stops.

## Inputs

- Branch state (commits ahead of `origin/main`, current diff)
- `checks.md` — the frozen manifest and the verifier's report
- `spec.md` — design decisions and the tier
- `plan.md` — referenced from the PR body

## Outputs

- Squashed branch pushed; PR opened with per-criterion results and the `agent-session:gate` block
- Review comments assessed and worthwhile ones fixed
- Final squash force-pushed (`--force-with-lease`), gate block refreshed
- **A gate verdict reported**: `eligible-for-auto-merge` or `human-merge-required` + reason

## Rebase and re-verify

1. **Rebase onto `origin/main` first.** `git fetch origin && git rebase origin/main`. Sessions
   run long and main advances; pre-rebase, `git diff origin/main..HEAD` can show dozens of
   unrelated files, drowning out your actual changes and corrupting both self-review and squash.
   Resolve conflicts now, not after the PR is open.

2. **Re-run the criteria's checks and the guards after the rebase**, even if they were green
   minutes ago. `origin/main` may have changed a fixture or behavior they depend on.

   **Re-anchor the freeze sha first.** A rebase rewrites the freeze commit, so the sha recorded
   in `checks.md` points outside the branch's history — diffing against it blends upstream
   changes into your tamper diff. Find the rebased freeze commit, confirm it's the same tree
   (`git diff <old> <new> -- <check files>` is empty), record the new sha, and diff against that.
   Then re-run the tamper check: a conflict resolution inside a frozen check file is an edit to
   a frozen check, whoever made it.


## Self-review

3. **Review `git diff origin/main..HEAD`** for:
   - **Bugs introduced:** wrong logic, missing imports, unintentionally changed behavior
   - **Incomplete changes:** renamed in one place, missed another; removed a function, left callers
   - **Edge cases:** hidden files not filtered, path traversal, off-by-one, empty inputs
   - **Test gaps:** new behavior without tests; changed behavior existing tests don't cover
   - **Convention violations:** bare error strings, imports inside functions, undeclared attributes
   - **Doc gaps:** new config options undocumented, CLAUDE.md key-files list stale
   - **Frozen-check edits:** any diff touching a path in `checks.md`'s `Check files`. If one
     appears here and isn't a logged amendment, stop — the green checks aren't evidence yet.

   Fix what you find. This catches what a bot reviewer misses, and vice versa.

## Squash and open

4. **Re-check `origin/main` immediately before squashing.** `git fetch origin && git log
   --oneline main..origin/main`. Main may have advanced again since the rebase, and a
   soft-reset-then-commit squash against a stale `origin/main` silently includes deletions of
   files that landed in between (a sibling PR merging is enough). If new commits appear, redo
   the rebase and re-verification.

5. **Run the tamper check, then squash.** In this order, because `git reset --soft origin/main`
   collapses the freeze commit away and the baseline becomes unreachable from the branch (the
   object survives locally until GC, but not for a reviewer or CI). So: run
   `git diff <freeze-sha> -- <check files>`, **record the verdict in `checks.md` and the gate
   block** — that record is the durable evidence the gate cites, since the command won't be
   reproducible afterwards. (Post-squash the freeze commit is a dangling local object: not an
   ancestor of the branch and absent from `origin`, so nobody else can re-run it. The record *is*
   the evidence.) If `Check files` is empty, run the substitutes from `frozen-checks.md`'s "When
   the criteria are commands, not test files" instead and record `clean-by-substitute` + its basis;
   the bare command proves nothing there. Then squash all branch commits into one with a comprehensive message,
   and **push**.

6. **Open the PR** using `references/pr-body-template.md`. Title under 70 chars. Fill the
   **Acceptance criteria** table from the *independent verifier's* report — never from the
   implementer's own run. Include `Closes #N`, links to `spec.md` / `checks.md` / `plan.md`, and
   the gate block.

   **Open with `verdict: pending`.** Two of the gate's rows — unresolved threads, and the
   verifier's post-review report — do not exist yet at this point, so any verdict written here is
   a guess. The block is machine-readable and a board-driver may read it at any moment; a
   provisional `eligible-for-auto-merge` sitting in the body through the whole review cycle is a
   window where an automated reader can act on a verdict nobody derived. Step 14 writes the real
   one.

7. **Board hook.** If a board is configured, move each `Closes #N` issue to `in_review`.
   Otherwise report `board: not configured` with the verdict — not a silent skip.

## Review cycle

8. **Record the current comment count as a baseline**, then **request a review**:
   ```
   gh pr edit <number> --add-reviewer copilot-pull-request-reviewer
   ```
   `gh api repos/{owner}/{repo}/pulls/{number}/comments --jq 'length'` — step 9 needs that number
   to tell a new comment from an existing one.

9. **Poll for new comments.** `gh api repos/{owner}/{repo}/pulls/{number}/comments --jq
   'length'` every 30s for up to 10 minutes; stop early once the count exceeds the pre-request
   baseline. Report a timeout if none arrive.

10. **Assess each comment:**
    - **Fix:** real bugs, valid edge cases, missing error handling, doc/code mismatches, test gaps
    - **Skip:** over-engineering, theoretical concerns without real risk, style nitpicks
    - **Defer:** real correctness issues that are pre-existing and outside this spec's scope.
      File a follow-up issue, link it from a PR comment, and note the deferral in the PR body's
      References. Don't silently skip a real-but-out-of-scope problem.
    - **A comment arguing a frozen check is wrong** does not authorize editing it. It's a
      reviewer's opinion, not an amendment — route it through
      `references/frozen-checks.md`'s amendment path, tier downgrade included.

    **Resolve a thread only when you fixed what it raised.** A thread you *disputed* stays open
    for a human, however confident the refutation. Otherwise "no unresolved review threads"
    becomes self-satisfiable — the agent overrules the reviewer, closes the thread, and reports
    a clean gate — and the condition stops meaning anything. Disputing is fine and often right;
    disputing *and* clearing your own gate is not. Reply with the evidence, leave it open.

11. **Fix worthwhile comments**, then re-run the criteria's checks (a fix can break a
    criterion), lint, and commit.

12. **Re-dispatch the independent verifier** if anything changed since the last report — a rebase
    re-verification or a review-cycle fix means the standing report describes an earlier tree, and
    every gate row below sources from *the verifier's* run, not the implementer's. Fresh context,
    `checks.md` and the repo only, per `references/frozen-checks.md`.

13. **Squash again and force-push** with `--force-with-lease` — it refuses if the remote has
    commits you haven't fetched, preventing silent overwrites of work pushed from another
    machine. Re-check `origin/main` first; main may have advanced during the poll-and-fix cycle.
    **Refresh the gate block** so it describes the pushed state.

## Merge gate

14. **Derive the verdict.** Not a judgment call — read each row and take the result:

    | Condition | Source |
    |---|---|
    | Every criterion with a check: `pass` | The independent verifier's report (step 12's, if it re-ran) |
    | Every human-judgment criterion: graded by a human | `checks.md` evidence + an actual human answer |
    | Every guard still `pass` | The verifier's report — a pass→fail flip is a regression you caused |
    | Tamper diff clean, or every difference logged as an amendment | The verdict recorded at step 5 (pre-squash) — `clean-by-substitute` counts, bare `clean` on an empty `Check files` list does not |
    | Local project gates green | `make check` in the worktree |
    | CI checks on the pushed head all pass | `gh pr checks` — the query below. A local `make check` is **not** a substitute |
    | No unresolved review threads | The GraphQL query below — there is no `--json reviewThreads` field |
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
    registering as a review — so check the review itself landed (`gh pr view <n> --json reviews`)
    rather than reading `0 unresolved` as proof a reviewer ran.

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

    Any row satisfied by a substitute rather than by its cited mechanism is still a pass, but
    **name the substitute in the gate block** where the row would otherwise read as a clean
    mechanical result. A row that silently reports the mechanism's absence as the mechanism's
    verdict is the one failure this table cannot survive.

    A `needs-review` tier is never eligible, however green the checks. That's the tier doing its
    job — it was set because something here isn't check-decidable.

15. **Stop.** Report the PR URL, the verdict + reason, what was fixed, and what was skipped or
    deferred. Do not merge — no `gh pr merge`, with or without `--auto`. `eligible-for-auto-merge` is a
    *finding*; the unattended loop that acts on it lives above this skill.

## When to skip

Work that won't end in a PR (direct-to-main, throwaway, keep-local) — see
`superpowers:finishing-a-development-branch` for the merge/PR/keep/discard pattern with the
right worktree cleanup for each.

Unfinished work and red checks are preconditions, not skip conditions: fix them, then run `pr`.
