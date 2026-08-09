# triage

Batch backlog-gardening: go back through a repo/board's existing issues, find the
under-specified ones, and augment them so they carry verifiable acceptance criteria + a
tier — turning a backlog of wishlist issues into a queue an autonomous loop can consume.

Reads the shared engine: `references/acceptance-criteria.md`, `references/spec-template.md`.
Reuses `phases/intake.md`'s *augment* logic per issue — same engine, batch-driven.

## Why subagents (the context lesson)

Reading and scoring dozens of issue bodies + their code context would flood the main
context. So the token-heavy work fans out to subagents that each work in their own context
and return only a compact result. The **human stays in the main loop** — subagents can't
interview you, so they do the part that needs no human (assess + *draft proposed*
criteria), and you do the part that does (ratify). See
`superpowers:dispatching-parallel-agents`.

## Process

1. **Scope the scan.** Get the candidate set — `gh issue list` filtered
   by label/board column/query (e.g. all open, or the Backlog column). Confirm the scope
   with the user before fanning out (a scan of 200 issues is a lot of subagents).

2. **Fan out assessment (subagents, parallel).** One subagent per issue (batched to a sane
   concurrency). Each subagent, in its own context:
   - reads the issue body,
   - scores spec-completeness: does it have a clear goal? verifiable acceptance criteria?
     is it already marked with the `agent-session:spec` label?
   - if under-specified, does light codebase research and **drafts *proposed* criteria +
     checks + guards + a tier** per `acceptance-criteria.md` — a proposal, not a commitment,
   - **runs each proposed check** and records what it observed, so the ratify pass knows which
     proposals discriminate (fail today = criterion) and which don't (pass today = guard). A
     subagent that only *reads* code will propose plausible checks that grade nothing,
   - **is told not to fudge a weak check to keep `auto-ok`.** `intake` carries this rule; a
     scanning subagent needs it too, or it will go proxy-hunting in good faith — greping for a
     keyword to "verify" a doc is accurate, or asserting a test exists to "verify" it covers
     something. An honest `needs-review` beats a checkable-looking proxy. Include the
     satisfiable-without-the-work test from `acceptance-criteria.md` in the subagent's brief,
   - returns a COMPACT result only: `{issue, score, already_specified, proposed_criteria,
     proposed_guards, proposed_tier, observed_check_results, open_questions}`. Not the raw issue
     body or research dump.

   The main context now holds a scored list, not dozens of issue bodies.

   **Cap what a scanning subagent may run.** "Run each proposed check" and "fan out in parallel"
   collide: N agents each invoking the project's full suite will thrash the machine, and a
   parallel test runner (`pytest -n auto`, `cargo test`, `go test ./...`) already claims every
   core on its own. Tell each subagent explicitly: **targeted commands only** — a single test
   node, a `grep`/`rg`, a one-line interpreter call — and **never `make test` / `make check` /
   the full suite**. A criterion that can only honestly be checked by the full suite gets marked
   UNRUN and verified once, serially, during the ratify pass.

   This is a real limit on what a batch scan can conclude, so state it rather than letting UNRUN
   read as verified. Also give each subagent read-only tools where the harness allows it — a
   scanner has no business editing the repo it's scoring.

3. **Headless proposal (Async ratify pass).** Because you are running autonomously, there is no user to pick from a table interactively. Instead, for the issue you scanned:
   - **Post your proposed EARS criteria, checks, and tier as a comment on the GitHub issue** using `gh issue comment <n> --body <text>`.
   - Apply the `agent-session:needs-human` label so the human knows they need to review it.
   - Do NOT apply the `agent-session:spec` label yet, because the human hasn't ratified the criteria.
   - Stop execution here. Do not edit the issue body yet.

   - In your comment, explicitly ask the human to reply with 'Approved' or to provide corrections, and instruct them to **manually remove the `agent-session:needs-human` label** when they are done replying so you know to read their feedback.

4. **Follow-up pass (Reading human replies).** The human has explicitly removed the `agent-session:needs-human` parking label, signaling that they have left feedback in the issue comments. Read the subsequent comments from the human.
   - If they explicitly approved the spec (e.g., "Approved", "Looks good", "Dependencies are fine"), proceed to Step 5.
   - If they provided corrections, synthesize them into an updated spec. If the spec is now complete, proceed to Step 5. 
   - If the spec STILL needs human input after synthesizing their corrections, post a follow-up comment asking for further clarification, RE-APPLY the `agent-session:needs-human` label, and stop.

5. **Write back (augment in place).** For each ratified issue, run `intake`'s file-or-update step.
   First ensure the label exists (`gh label create "agent-session:spec" --color 0E8A16 || true`).
   Then the *existing-issue* path: `gh issue edit <n>` — add the `agent-session:spec` label (`--add-label`), add the verifiable
   criteria + tier sections, **preserving the original author's
   text**. Update the board if configured. Where the ratify pass settled a decision, carry
   `intake`'s Design-decisions step with it — the body, not a comment; comments are invisible
   to every downstream mode.

   **The `## Tier:` heading is replaced, never added twice.** An issue that already carries one — and
   a re-tiered issue always does — gets that heading edited in place. Two `## Tier:` headings read as
   a conflict and the issue is skipped, silently from the author's side. Keep superseded reasoning
   only under a heading the anchor does not match. Format per `acceptance-criteria.md` → "The heading
   format is part of the contract".

   **Verify the write-back rather than trusting it:** re-read each edited body and confirm the
   author's original text survives as a substring of it, and that exactly one `## Tier:` heading
   remains. Both failures are invisible by eye on a long body.

6. **Report** a summary: scanned N, already-specified M, augmented K (with tiers), left
   under-specified (and why — e.g. needs a design decision only the user can make).

## Escalation — stop and surface when

- An issue's intent is genuinely unclear (not just under-specified) → leave a GitHub comment explaining the ambiguity, apply the `agent-session:needs-human` label, and stop.
- The scan surfaces duplicate/obsolete issues → comment suggesting closure, apply `agent-session:needs-human`, and stop.
- An issue requires subjective visual/aesthetic iteration (like layout density, game feel, or UI design) → apply the `agent-session:needs-human-interactive` label instead. These cannot be handled asynchronously; they require an interactive prototype session in the CLI.
- A subagent can't tell what "done" would mean → comment asking the human for direction, apply `agent-session:needs-human`, and stop.
