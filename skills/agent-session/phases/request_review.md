# request_review

A stateless phase for the unattended agent-session driver. It is invoked when an open PR has passed CI but has no reviews and no reviewers requested.

Your task is to assign or request a review on the PR so it can progress.

## Process
1. Check the PR (`gh pr view <n>`) to see the context.
2. Request a review from the appropriate user/team. If no specific user is known, request a review from `@lmorchard` or the repository owner.
   Record a `pr_edit` entry with `add_reviewer` — see `references/write-manifest.md`. You cannot
   run the write yourself; your GitHub credential is read-scoped.
3. Stop and output a summary. No PR gate block is needed as you are just updating PR metadata.
