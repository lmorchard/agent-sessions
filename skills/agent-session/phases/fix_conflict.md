# fix_conflict

Fix Git merge conflicts on an open PR.
This phase is triggered by the orchestrator when a PR has merge conflicts with its base branch (usually `main`).

## Inputs
- GitHub PR URL
- The GitHub issue this resolves
- `checks.md` (if available, for large/architectural tasks)
- `spec.md` (if available)

## Outputs
- Commits pushed resolving the merge conflicts.
- Gate block refreshed.

## Process

1. **Assess the conflict:**
   Use Git to fetch the latest changes from the base branch (e.g. `main`) and the PR branch.
   Run `git merge main` or `git rebase main` to trigger the conflict locally.
   Identify which files are conflicting and read the conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`).

2. **Resolve the conflict:**
   Carefully edit the conflicting files to integrate both sets of changes.
   Ensure that the project's invariants, tests, and standard behavior still pass. Run the project's local test suite and lint checks (e.g., `make check` or `make test`) to verify the resolution.

3. **Re-dispatch the independent verifier** if anything changed significantly during the conflict resolution that requires re-verification.

4. **Push the resolved code.** 
   Commit the resolved files. If you used `git rebase`, push with `--force-with-lease`. If you used `git merge`, perform a standard push.
   **Refresh the gate block** so it describes the pushed state.

5. **Stop.** Exit so the orchestrator can wait for CI to re-evaluate the state.
