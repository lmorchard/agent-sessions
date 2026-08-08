# open_pr

Self-review, push, open a PR, run the review cycle, and **stop at the merge gate**.

Reads `references/frozen-checks.md` (gate condition), `references/pr-body-template.md` (body +
gate block), `references/github-projects.md` (board hook).

The gate is where this mode ends: it reports whether the gate is satisfied and stops.

## Inputs

- Branch state (commits ahead of `origin/main`, current diff)
- The GitHub issue this resolves
- `checks.md` (if available, for large/architectural tasks)
- `spec.md` (if available)

## Outputs

- Branch pushed; PR opened with a gate block (simplified for small tasks).
- **A gate verdict reported**: `eligible-for-auto-merge` or `human-merge-required` + reason

## Process

0. **Ceremony Threshold:** If this is a small/tactical task, there won't be a `checks.md` or a freeze commit. Skip steps related to the tamper diff and frozen manifest. Do the self-review, run tests (`make check`), push, and open the PR. Write a gate block exactly as shown in the template, making sure to include the `<!-- agent-session:gate -->` HTML comment before the ```yaml code block following `references/pr-body-template.md` with all required fields (`tier`, `checks`, `guards`, `tamper`, `freeze`, `project-gates`, `ci`, `threads`, `risk-paths`, `verdict`, `reason`). Use `freeze: <commit-sha>` (or `freeze: none` if no freeze commit exists) and `tamper: clean`. Only proceed with the full tamper-diff and frozen-check rules if those artifacts exist.

1. **Rebase onto `origin/main` first.** `git fetch origin && git rebase origin/main`. Sessions
   run long and main advances; pre-rebase, `git diff origin/main..HEAD` can show dozens of
   unrelated files, drowning out your actual changes and corrupting the self-review diff.
   Resolve conflicts now, not after the PR is open.

2. **Re-run local checks and guards after the rebase**, even if they were green
   minutes ago. `origin/main` may have changed a fixture or behavior they depend on.

   **(If using frozen checks) Re-anchor the freeze sha first.** A rebase rewrites the freeze commit, so the sha recorded
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

## Push and open

4. **Re-check `origin/main` immediately before pushing.** `git fetch origin && git log
   --oneline main..origin/main`. Main may have advanced again since the rebase, and everything you
   verified was verified against the older base. If new commits appear, redo the rebase and
   re-verification.

5. **(If using frozen checks) Run the tamper check, record the verdict, and push the branch as-is.** Run
   `git diff <freeze-sha> -- <check files>` and **record the verdict in `checks.md` and the gate
   block**. If `Check files` is empty, run the substitutes from `frozen-checks.md`'s "When the
   criteria are commands, not test files" instead and record `clean-by-substitute` + its basis; the
   bare command proves nothing there.

   If skipping the frozen checks ceremony, simply push the branch.

   **Do not squash the branch.** The freeze commit must stay an ancestor of the pushed head, because
   that is what lets somebody other than the implementer re-run the tamper diff. `git reset --soft
   origin/main` orphans it — the object survives locally until GC, but it is absent from `origin`, so
   the recorded verdict becomes a claim the run made about itself rather than a command a reviewer can
   check. Leave history alone and let the merge button decide its shape.

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


8. **Request a review**:
   ```
   gh pr edit <number> --add-reviewer copilot-pull-request-reviewer
   ```
   
9. **Stop.** State that the PR is open, review requested, and exit so the orchestrator can wait for CI or comments.
