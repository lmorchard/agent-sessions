# Spec: Driver distributed git-ref locking for issue contention (#156)

## Problem Statement
As the driver moves toward a stateless reconciliation loop, multiple independent agents (or overlapping cron jobs) can wake up and select the same issue for triage or execution simultaneously. Because the GitHub API has no atomic "Compare-And-Swap" issue assignment, this creates a TOCTOU (Time-Of-Check-To-Time-Of-Use) race condition, resulting in duplicated LLM budget spend and duplicated GitHub comments.

## Proposed Solution
Implement a host-agnostic, distributed lock using Git references (`refs/locks/issue-$N`). Because `git push` is atomic at the remote, agents can use it as a mutex.

1. **Acquire**: Generate an empty, detached commit containing metadata (`phase`, `host`, `run_id`). `git push $SHA:refs/locks/issue-$N`.
2. **Steal**: If the lock exists, fetch the commit to check its age. If it exceeds the TTL (e.g., 10 mins for triage, 2 hrs for execute), use `git push --force-with-lease` to atomically steal it.
3. **Release**: When the phase completes, delete the remote ref: `git push origin :refs/locks/issue-$N`.

## Acceptance Criteria
- [ ] The driver attempts to acquire a git ref lock immediately after popping an issue from its priority queue.
- [ ] If the lock fails, the driver gracefully skips the issue and attempts to lock the next one.
- [ ] Stale locks are successfully stolen using `--force-with-lease` and timestamp evaluation.
- [ ] The driver always attempts to release the lock in an exit trap.

## Tier: `needs-review`
Modifies `driver/agent-session-driver.sh`, which is risk-gated.
