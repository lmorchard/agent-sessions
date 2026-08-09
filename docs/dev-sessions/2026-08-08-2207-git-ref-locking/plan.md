# Plan: Distributed Git-Ref Locking (#156)

## Overview
Implement host-agnostic, distributed lock using Git references (`refs/locks/issue-$N`) in `driver/agent-session-driver.sh`.

## Proposed Changes

### 1. Lock Functions in `driver/agent-session-driver.sh`
- `acquire_lock()`:
  - Generates detached commit using `git commit-tree` against empty tree SHA (`4b825dc642cb6eb9a060e54bf8d69288fbee4904`) with structured commit message (issue, phase, host, run_id).
  - Checks remote ref (`git ls-remote origin refs/locks/issue-$ISSUE`).
  - If absent: `git push origin $lock_sha:refs/locks/issue-$ISSUE`.
  - If present: fetches lock ref, inspects timestamp (%ct) and age against TTL (10m for triage/groom, 2h for execute/others).
  - If stale: attempts CAS steal via `git push --force-with-lease=refs/locks/issue-$ISSUE:$current_lock origin $lock_sha:refs/locks/issue-$ISSUE`.
- `release_lock()`:
  - Deletes remote ref: `git push origin :refs/locks/issue-$ISSUE`.

### 2. Integration into Selection Loop
- When selecting an issue from `p1_unblock`, `p2_execute`, or `p3_groom`:
  - Instead of unconditionally taking the first item, iterate through candidates in priority order.
  - For each candidate, attempt `acquire_lock`.
  - If acquisition succeeds, set `ELIGIBLE` and break the loop.
  - If acquisition fails due to contention, log and try the next candidate.
  - If all candidates are locked, report no eligible work and exit gracefully.

### 3. Cleanup Trap
- Register `release_lock` (for the currently held lock) in an exit trap (`trap '...' EXIT INT TERM`) so locks are never orphaned on driver crash/exit.

## Verification
- Unit/integration testing via driver stub test suites (`test-driver.sh`).
