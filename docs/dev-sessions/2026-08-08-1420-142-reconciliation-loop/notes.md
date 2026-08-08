# Notes: Epic #142 (Global Reconciliation Loop)

## Priority Ladder Implementation
Rewrote `select_issues()` in `driver/agent-session-driver.sh` to classify all candidates into 4 buckets according to the priority ladder:
1. **Priority 1 (Unblock)**: PRs that are stuck (`address_comments`, `fix_ci`, `request_review`, `grade_gate`).
2. **Priority 2 (Execute)**: `execute` for `tier: auto-ok` issues.
3. **Priority 3 (Groom)**: `triage` for marker-less issues and `refine` for `tier: needs-review` issues.
4. **Priority 4 (Escalate)**: Escalated issues.

The queue stops accumulating immediately and instead selects exactly ONE eligible item from the highest non-empty bucket.

## Escalation and Notification
Introduced `notify_human()` in `driver/agent-session-driver.sh` which records to `$STATE_DIR/inbox.md`, `ntfy.sh/$NTFY_TOPIC`, and `$EMAIL_ALERTS` dynamically based on configuration.
This is hooked directly into `apply_park_state()` for parked/loop breaker escalations, and specifically intercepts `gate-human` terminal outcomes to invoke a manual review alert. 

## Refine & Request Review Phases
Added `skills/agent-session/phases/refine.md` and `skills/agent-session/phases/request_review.md` to cleanly handle these steps without breaking stateless constraints.

## Tests
Adapted `driver/test-driver.sh` to account for the fact that `triage` handles marker-less issues correctly and added a new check `loop breaker parks the issue and notifies inbox` asserting that an in-flight loop-breaking issue calls the new escalation pathway.
