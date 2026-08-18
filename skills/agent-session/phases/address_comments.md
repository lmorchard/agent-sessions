# address_comments

Address unresolved review threads on an open PR. 
This phase is triggered by the orchestrator when a PR has open review comments.

## Inputs
- GitHub PR URL
- The GitHub issue this resolves
- `checks.md` (if available, for large/architectural tasks)
- `spec.md` (if available)

## Outputs
- Commits pushed addressing valid review comments.
- Gate block refreshed.

## Process

1. **Assess each unresolved comment:**
   The unresolved review threads have been provided in your context.
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

2. **Fix worthwhile comments**, then re-run the criteria's checks (a fix can break a
   criterion), lint, and commit.

3. **Re-dispatch the independent verifier** if anything changed since the last report — a review-cycle fix means the standing report describes an earlier tree, and
   every gate row below sources from *the verifier's* run, not the implementer's. Fresh context,
   `checks.md` and the repo only, per `references/frozen-checks.md`.

4. **Push the review fixes.** Re-check `origin/main` first; main may have advanced during the
   poll-and-fix cycle. **Refresh the gate block** so it describes the pushed state.

   **Still no squash** — the freeze commit has to survive to the gate. If a rebase became necessary here,
   push with `--force-with-lease`, never bare `--force`: it refuses when the remote has commits you
   haven't fetched, which prevents silently overwriting work pushed from another machine.

5. **Stop.** Exit so the orchestrator can re-evaluate the state.
