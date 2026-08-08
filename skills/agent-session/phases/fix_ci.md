# fix_ci

Fix failing CI checks on an open PR.
This phase is triggered by the orchestrator when a PR has failing CI checks.

## Inputs
- GitHub PR URL
- The GitHub issue this resolves
- `checks.md` (if available, for large/architectural tasks)
- `spec.md` (if available)

## Outputs
- Commits pushed addressing the CI failures.
- Gate block refreshed.

## Process

1. **Assess the CI failures:**
   Fetch the failed CI checks using `gh pr checks <n> --failed`.
   Read the logs of the failed jobs to understand the root cause. If necessary, use `gh run view` to see the logs.
   
   If the failure is a known flake or infrastructural issue unrelated to your changes, note this and stop without making code changes.

2. **Fix the code:**
   Make the necessary adjustments to the code to resolve the CI failures. Ensure you run local equivalents of the failing checks (e.g. `make test` or `make lint`) to verify your fix locally before committing.

3. **Re-dispatch the independent verifier** if anything changed since the last report. Fresh context, `checks.md` and the repo only, per `references/frozen-checks.md`.

4. **Push the review fixes.** Re-check `origin/main` first; main may have advanced. **Refresh the gate block** so it describes the pushed state.
   **Still no squash** — the freeze commit has to survive to the gate. If a rebase became necessary here, push with `--force-with-lease`.

5. **Stop.** Exit so the orchestrator can wait for CI to re-evaluate the state.
