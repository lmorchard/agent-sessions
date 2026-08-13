# rethink

Retire a failed execution attempt cleanly, preserve its lessons, and drop smoothly back into the `intake` interview to draft a new spec.

This is a human-in-the-loop phase, typically triggered interactively when an operator inspects an issue that the autonomous `execute` phase has parked with `agent-session:needs-human` due to a fundamental structural mismatch or dead end.

## Inputs

- A GitHub issue URL (which currently holds an active `<!-- agent-session:spec -->` and a failed approach).
- The human operator's context on *why* it failed and what the *new* direction should be.

## Outputs

- The issue body updated with the old spec wrapped in a "Superseded" tombstone block.
- A seamless transition into the `intake` phase to write the new spec.
- Removal of the `agent-session:needs-human` label (via the final `intake` write), which un-parks the issue for the autonomous driver.

## Process

1. **Fetch the current issue.** Read the issue body (`gh issue view <url> --json body`). Identify the active spec sections (Goal, Acceptance Criteria, Regression Guards, Design Decisions, Tier) and the `<!-- agent-session:spec -->` marker.

2. **Harvest the Learnings.** Ask the user: *"What did we learn from the failed attempt, and what is the new direction?"* This ensures the pivot is grounded and explicitly captures the failure mode as a new constraint.

3. **Tombstone the Old Spec.** 
   - Wrap the entire active spec inside a Markdown details block: `<details><summary>Superseded Spec (Attempt N: [Brief description])</summary> ... </details>`. 
   - **CRITICAL:** Inside the tombstone block, replace the `<!-- agent-session:spec -->` marker with `<!-- agent-session:spec-RETIRED -->`. If the active marker remains, the driver's routing query will still see the issue as "specced" and incorrectly route it back to `execute` with the old tier.

4. **Clean up Local State.** 
   - If there is a known local worktree or session directory for the failed attempt, explicitly advise the user to delete it or abandon the branch. The new attempt must start from a clean slate so that old frozen checks (`checks.md`) do not pollute the new path.

5. **Pivot to Intake.**
   - Immediately transition to the `intake` phase logic (`phases/intake.md`), starting at step 2 (Codebase research) or step 3 (Interview). 
   - **Prime the context:** Explicitly carry forward the user's answer from Step 2 as the primary constraint for the new spec. The prompt to yourself for the `intake` interview should be: *"We are re-specifying this issue. The previous attempt failed because [Learnings]. Guide the user to write new verifiable criteria that satisfy the original goal while avoiding the failed approach."*

6. **Finalize and Un-park.**
   - When the `intake` phase finishes and you update the issue body with the new spec, ensure that the `agent-session:needs-human` label is explicitly removed by recording a `label` entry in the write manifest (`{"kind": "label", "issue": <number>, "remove": ["agent-session:needs-human"]}`). 
   - This label removal, combined with the new `<!-- agent-session:spec -->` marker, signals to the autonomous driver that the issue is ready to be picked up for a fresh `plan` phase.
