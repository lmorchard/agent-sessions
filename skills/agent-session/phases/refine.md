# refine

A stateless phase for the unattended agent-session driver. It takes a `tier: needs-review` issue and attempts to rewrite its acceptance criteria into automatable checks, upgrading it to `auto-ok` so the execution loop can pick it up. If it cannot reliably automate the checks, it does nothing, leaving the issue in `needs-review` so it can escalate to a human.

## Process

1. **Understand the intent.** Read the target issue body (`gh issue view <n>`). Understand *why* it is currently `needs-review`. Look for subjective criteria (like visual design or human validation) or high-risk paths (infrastructure changes, migrations).

2. **Evaluate automatability.** Can the criteria be replaced by a concrete, runnable test command (`pytest`, `make test`, `bash` assertions) that provides equal confidence? 
   - **Yes (Automable):** Rewrite the acceptance criteria into Given/When/Then + Check format (per `references/acceptance-criteria.md`).
   - **No (Subjective/High-Risk):** Stop immediately. Output a summary stating that the issue requires human judgment or review and cannot be automated. Do not edit the issue.

3. **Verify the new checks.** If you drafted new checks, you MUST verify that they are runnable *right now* and fail (because the issue is not implemented yet). 
   - Run the proposed check command.
   - If it passes (which means it's a guard, not a criterion) or errors due to missing fixtures, fix it or revert to `needs-review`.

4. **Rewrite the issue body (if upgraded).** If you successfully drafted automated criteria that fail:
   - Rewrite the entire issue body.
   - Change `## Tier: needs-review` to `## Tier: auto-ok`.
   - Replace the old criteria with your new verifiable criteria + checks.
   - PRESERVE the original author's description and context text verbatim. Do not delete their context.
   - Update the issue using `gh issue edit <n> --body "<body>"`.

5. **Stop.** Output a concise summary of the outcome (Upgraded to auto-ok OR Left as needs-review). No PR gate block is needed for `refine` since no code was committed. The driver will read the updated tier on its next loop.
