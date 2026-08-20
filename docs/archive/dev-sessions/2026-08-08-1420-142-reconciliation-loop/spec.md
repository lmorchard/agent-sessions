# Epic: Global Repository Reconciliation Loop & Active Escalation

## The problem
Epic #141 (Wiggum Architecture) introduced stateless phases and dynamic routing for in-flight PRs, but the driver still behaves as a simple execution queue processor. It drops raw or `needs-review` issues and relies on passive escalation (labeling an issue `driver-parked` and hoping a human notices). 

To become a true autonomous repository operator, the system must continually evaluate the entire board, pick the single highest-leverage action to advance the project state, attempt to unblock itself, and proactively notify a human when genuinely stuck.

## The solution
1. **Priority Ladder (The Loop)**: Redesign the driver's selection stage to evaluate all open issues/PRs and pick ONE action based on this priority:
   - *Priority 1 (Unblock)*: `address_comments`, `fix_ci`, `request_review` (for PRs without automatic reviews configured, request from copilot/claude/human), `grade_gate` for open PRs.
   - *Priority 2 (Execute)*: `execute` for `tier: auto-ok` issues.
   - *Priority 3 (Groom)*: `triage` for raw issues, and a new `refine` phase for `tier: needs-review` issues.
   - *Priority 4 (Escalate)*: Proactively notify the human for blocked items.
2. **The `refine` Phase**: A new stateless phase that takes a `needs-review` issue and attempts to rewrite its acceptance criteria into automatable checks. If successful, it upgrades the tier to `auto-ok`. If it fails (e.g., destructive infrastructure changes or visual design checks), it routes to escalation.
3. **Flexible Active Notification**: Replace passive parking with a multi-channel notification system. When the loop breaker fires, a PR is graded `human-merge-required`, or a refinement fails:
   - Send a push notification (via `ntfy` for mobile).
   - Support email routing.
   - Append to a durable local "inbox" (e.g., `STATE_DIR/inbox.md` or a central agent dashboard) for batch review at the keyboard.

## Acceptance criteria
- **CRITERION 1:** GIVEN the driver runs against a mixed queue of raw, `auto-ok`, and open PR issues, THEN it SHALL select the highest priority action according to the ladder.
  **CHECK:** New driver fixture tests in `driver/test-driver.sh` asserting the correct phase selection across a mixed queue.
- **CRITERION 2:** GIVEN a `tier: needs-review` issue due to un-automatable criteria, WHEN the `refine` phase runs, THEN it SHALL attempt to replace them with checkable assertions (like `pytest` or `make check`) and rewrite the issue body.
  **CHECK:** Evaluate the `refine` prompt against a known fixture issue and assert the tier is upgraded to `auto-ok` and criteria are updated.
- **CRITERION 3:** GIVEN an issue that triggers a loop breaker (e.g. `MAX_PHASE_ATTEMPTS`), WHEN the driver parks it, THEN it SHALL dispatch a notification payload to the configured channels (ntfy/inbox).
  **CHECK:** Mock the notification endpoint/script in the driver tests and assert it is invoked with the issue details when the loop breaker branch executes.