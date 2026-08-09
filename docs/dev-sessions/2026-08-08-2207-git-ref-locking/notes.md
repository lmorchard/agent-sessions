# Notes: Distributed Git-Ref Locking (#156)

## Summary of Work
- Implemented distributed Git ref locks (`refs/locks/issue-$N`) in `driver/agent-session-driver.sh`.
- Added `acquire_lock` with structured commit message (issue, phase, host, run_id), empty tree commit-tree generation, TTL checks (10m for triage/groom/refine, 2h for others), and Compare-And-Swap stealing via `--force-with-lease`.
- Added `release_lock` and integrated it into the driver's exit/int/term cleanup trap.
- Updated `select_issues()` to iterate through candidates in priority order and attempt lock acquisition, gracefully skipping contested issues.
- Updated explicit `--issue <n>` path to require and acquire lock or fail with contention message.
- Verified all driver tests (`make driver-test`, 123 tests passed) and docs checks.
