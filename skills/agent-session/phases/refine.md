# refine

A stateless phase for the unattended agent-session driver. It takes a `tier: needs-review` issue and attempts to rewrite its acceptance criteria into automatable checks, upgrading it to `auto-ok` so the execution loop can pick it up. If it cannot reliably automate the checks, it does nothing, leaving the issue in `needs-review` so it can escalate to a human.

## Process

1. **Understand the intent & check comments/reactions.** Read the target issue body and comments (`gh issue view <n> --json comments` or `gh api graphql`). Understand *why* it is currently `needs-review`. Look for subjective criteria or high-risk paths (dependencies, migrations). Check if the human explicitly approved the risk-gated decision in the comments or via a 👍 reaction on the proposal comment (e.g., 👍 reaction, "Adding dependencies is fine", "Approved").

2. **Evaluate automatability & human approval.**
   - **Approved by human:** If the human explicitly approved the risk-gated path in the comments or via a 👍 reaction on the proposal comment, or if the criteria can be replaced by runnable test commands (`pytest`, `make test`, `bash`), upgrade the issue to `auto-ok`.
   - **Unapproved High-Risk/Subjective:** Stop immediately. Output a summary stating that the issue requires human judgment/review and cannot be automated. Record a `label` entry ensuring `agent-session:needs-review` is set.

3. **Verify the new checks.** If you drafted new checks, verify that they are runnable *right now* and fail (because the issue is not implemented yet).

4. **Apply Tier Label & Update Issue.** If upgraded to `auto-ok`:
   - Record a `label` entry adding `agent-session:auto-ok` and removing `agent-session:needs-review` (`references/write-manifest.md`).
   - Replace the criteria with verifiable criteria + checks in the issue body.
   - PRESERVE the original author's description and context text verbatim.
   - Record the new body as an `issue_body` entry. The driver applies it after your run, so check the string before you record it — you will not see the result.

5. **Stop.** Output a concise summary of the outcome (Upgraded to auto-ok OR Left as needs-review). No PR gate block is needed for `refine` since no code was committed. The driver will read the updated tier on its next loop.
