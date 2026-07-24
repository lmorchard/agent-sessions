# pr

Self-review, squash, push, open a PR, run the review cycle, and **stop at the merge gate**.

Reads `references/frozen-checks.md` (gate condition), `references/pr-body-template.md` (body +
gate block), `references/github-projects.md` (board hook).

The gate is where this mode ends. **This skill never merges a PR and never enables auto-merge.**
It reports whether the gate is satisfied; acting on that is a human's or the board-driver's job.

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

   **Expect guards pinned to absolute numbers to trip here.** Upstream adds tests, so a guard
   written as `3234 passed` goes stale while the property it protects — nothing lost, newly
   skipped, or newly failing — still holds. That's a mis-stated guard, not a regression: restate
   it as the invariant and log a clarification. Better, don't pin counts at intake.

3. **Run the tamper check before squashing, and record the result.** `git reset --soft
   origin/main` collapses the freeze commit away, so afterwards the baseline is unreachable from
   the branch (the object survives locally until GC, but not for a reviewer or CI). The tamper
   verdict recorded in `checks.md` and the gate block is the durable evidence — or keep the
   freeze commit as the PR's first commit instead of squashing it away.

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

5. **Squash** all branch commits into one with a comprehensive message, and **push**.

6. **Open the PR** using `references/pr-body-template.md`. Title under 70 chars. Fill the
   **Acceptance criteria** table from the *independent verifier's* report — never from the
   implementer's own run. Include `Closes #N`, links to `spec.md` / `checks.md` / `plan.md`, and
   the gate block.

7. **Board hook.** If a board is configured, move each `Closes #N` issue to `in_review`. Skip
   silently otherwise.

## Review cycle

8. **Request a review:**
   ```
   gh pr edit <number> --add-reviewer copilot-pull-request-reviewer
   ```
   That slug is the current GitHub-published bot identity; if it's renamed or this install uses
   a different one, the command silently no-ops. Confirm with `gh api
   repos/{owner}/{repo}/assignees | jq '.[] | select(.type=="Bot")'` if unsure.

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

12. **Squash again and force-push** with `--force-with-lease` — it refuses if the remote has
    commits you haven't fetched, preventing silent overwrites of work pushed from another
    machine. Re-check `origin/main` first; main may have advanced during the poll-and-fix cycle.
    **Refresh the gate block** so it describes the pushed state.

## Merge gate

13. **Derive the verdict.** Not a judgment call — read each row and take the result:

    | Condition | Source |
    |---|---|
    | Every criterion with a check: `pass` | The independent verifier's report |
    | Every human-judgment criterion: graded by a human | `checks.md` evidence + an actual human answer |
    | Every guard still `pass` | The verifier's report — a pass→fail flip is a regression you caused |
    | Tamper diff clean, or every difference logged as an amendment | `git diff <freeze-sha> -- <check files>` |
    | Project gates green | `make check` on the pushed head |
    | No unresolved review threads | `gh pr view <n> --json reviewThreads` |
    | Tier is `auto-ok` (and not downgraded by an amendment) | `spec.md` Tier section |
    | PR touches no risk-gated path | The diff vs. `acceptance-criteria.md`'s risk list |

    **All true → `eligible-for-auto-merge`. Any false → `human-merge-required`**, with the
    failing row as the reason. Write the verdict into the gate block and report it.

    A `needs-review` tier is never eligible, however green the checks. That's the tier doing its
    job — it was set because something here isn't check-decidable.

14. **Stop.** Report the PR URL, the verdict + reason, what was fixed, and what was skipped or
    deferred. Do not merge. Do not run `gh pr merge`, with or without `--auto`. `eligible-for-
    auto-merge` is a *finding*; the unattended loop that acts on it lives above this skill.

## When to skip

Work that won't end in a PR (direct-to-main, throwaway, keep-local) — see
`superpowers:finishing-a-development-branch` for the merge/PR/keep/discard pattern with the
right worktree cleanup for each.

Unfinished work and red checks are preconditions, not skip conditions: fix them, then run `pr`.
